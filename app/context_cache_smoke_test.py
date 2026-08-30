"""
Test dymny context_cache.py — kesz projektów/etapów + bazy wiedzy, odświeżany
rzadko (domyślnie raz na 24h), per rola. Decyzja właściciela 30.08.2026: boty
oceniające (bramka) i subagenci mają zawsze znać projekt/etap zadania i wiedzę
konkretnego agenta.

Zero sieci: klient to atrapa licząca wywołania. Izoluje context_cache.CACHE_DIR.

Użycie:
    python context_cache_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import context_cache as cc

PROJEKTY = [
    {"id": "PRJ-1", "name": "LDIT", "stages": [{"id": "ETAP-1", "name": "MVP"}, {"id": "ETAP-2", "name": "Poprawki"}]},
]
WIEDZA = {"entries": [
    {"id": "K-1", "title": "Zasady deweloperskie", "content": "Każda zmiana to osobny branch.", "updatedAt": "2026-08-20T00:00:00Z"},
    {"id": "K-2", "title": "Nowszy wpis", "content": "Najnowsza wiedza.", "updatedAt": "2026-08-29T00:00:00Z"},
]}


class _FakeClient:
    def __init__(self, boom=False):
        self.wywolania = 0
        self.boom = boom

    def list_projects_with_stages(self):
        self.wywolania += 1
        if self.boom:
            raise RuntimeError("Symulowany błąd sieci Projectly.")
        return PROJEKTY

    def get_knowledge_base(self):
        return WIEDZA


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_cache_dir = cc.CACHE_DIR

    try:
        tmp = Path(tempfile.mkdtemp())
        cc.CACHE_DIR = tmp

        # --- 1. Brak kesza -> odświeża, zapisuje na dysk. ---
        client = _FakeClient()
        kesz = cc.refresh_if_stale(client, role="test")
        checks.append(("refresh_if_stale: brak kesza -> odświeża (1 wywołanie klienta)", client.wywolania == 1))
        checks.append(("refresh_if_stale: kesz niesie projekty", kesz["projects"] == PROJEKTY))
        checks.append(("refresh_if_stale: kesz niesie wiedzę", len(kesz["knowledge"]) == 2))
        checks.append(("refresh_if_stale: zapisany na dysk (per rola)", cc._cache_path("test").exists()))

        # --- 2. Świeży kesz -> BRAK ponownego odświeżenia. ---
        kesz2 = cc.refresh_if_stale(client, role="test")
        checks.append(("refresh_if_stale: świeży kesz -> BRAK ponownego wywołania klienta",
                       client.wywolania == 1 and kesz2["projects"] == PROJEKTY))

        # --- 3. force=True -> odświeża mimo świeżości. ---
        cc.refresh_if_stale(client, role="test", force=True)
        checks.append(("refresh_if_stale: force=True odświeża mimo świeżości", client.wywolania == 2))

        # --- 4. Kesz "stary" (fetched_at sprzed >24h) -> odświeża. ---
        import json
        from datetime import datetime, timedelta, timezone
        stary = {"fetched_at": (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat(),
                 "projects": [], "knowledge": []}
        cc._save(stary, cc._cache_path("test2"))
        cc.refresh_if_stale(client, role="test2")
        checks.append(("refresh_if_stale: kesz starszy niż max_age_hours -> odświeża",
                       client.wywolania == 3))

        # --- 5. Fail-soft: błąd sieci -> zostaje przy STARYM keszu, bez wyjątku. ---
        client_boom = _FakeClient(boom=True)
        cc.refresh_if_stale(client_boom, role="test3", force=False)  # brak kesza jeszcze -> EMPTY_CACHE
        wynik_boom_pusty = cc.refresh_if_stale(client_boom, role="test3", force=True)
        checks.append(("refresh_if_stale: błąd sieci, brak wcześniejszego kesza -> EMPTY_CACHE, bez wyjątku",
                       wynik_boom_pusty["projects"] == [] and wynik_boom_pusty["knowledge"] == []))

        cc._save({"fetched_at": datetime.now(timezone.utc).isoformat(), "projects": PROJEKTY, "knowledge": []},
                 cc._cache_path("test4"))
        wynik_boom_stary = cc.refresh_if_stale(client_boom, role="test4", force=True)
        checks.append(("refresh_if_stale: błąd sieci, MA wcześniejszy kesz -> zostaje przy starym",
                       wynik_boom_stary["projects"] == PROJEKTY))

        # --- 6. project_and_stage_text: projekt+etap, sam projekt, nieznany -> ''. ---
        checks.append(("project_and_stage_text: projekt+etap",
                       cc.project_and_stage_text(kesz, "PRJ-1", "ETAP-2") == "Projekt: LDIT, Etap: Poprawki"))
        checks.append(("project_and_stage_text: sam projekt (brak stage_id)",
                       cc.project_and_stage_text(kesz, "PRJ-1") == "Projekt: LDIT"))
        checks.append(("project_and_stage_text: nieznany projekt -> ''",
                       cc.project_and_stage_text(kesz, "PRJ-NIEZNANY") == ""))

        # --- 7. knowledge_digest_text: najnowsze pierwsze, ograniczone limitem. ---
        digest = cc.knowledge_digest_text(kesz, limit=1)
        checks.append(("knowledge_digest_text: NAJNOWSZY wpis pierwszy (limit=1)",
                       "Nowszy wpis" in digest and "Zasady deweloperskie" not in digest))
        checks.append(("knowledge_digest_text: pusty kesz -> ''", cc.knowledge_digest_text(None) == ""))

        # --- 8. context_block: łączy oba, pomija puste części. ---
        blok = cc.context_block(kesz, {"project_id": "PRJ-1", "stage_id": "ETAP-1"})
        checks.append(("context_block: zawiera projekt+etap ORAZ digest wiedzy",
                       "Projekt: LDIT, Etap: MVP" in blok and "Nowszy wpis" in blok))
        checks.append(("context_block: brak project_id/kesza -> pusty string",
                       cc.context_block(None, {}) == ""))
    finally:
        cc.CACHE_DIR = original_cache_dir

    print("\n--- Wynik testu dymnego context_cache ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
