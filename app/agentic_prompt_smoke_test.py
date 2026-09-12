"""
Test dymny agentic_prompt.py — kolejnosc blokow promptu subagenta.

Sedno: ZASADY PROJEKTU (z Projectly, MCP zbot_get_project_policy) maja stac
NA POCZATKU promptu, przed kontekstem firmy i przed trescia zadania. Decyzja
wlasciciela 12.09.2026: to jest wiedza pierwszorzedna.

Zero sieci: klient Projectly to atrapa, kontekst firmy podmieniony.

Uzycie:
    python agentic_prompt_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import agentic_prompt

TASK = {"task_id": "T-1", "title": "Wyslij podsumowanie", "project_id": "P-1",
        "expected_result": "Podsumowanie", "acceptance_criteria": "Jest plik"}
PLAN = "Zrobie X, potem Y."

POLITYKA = {
    "projectName": "Strona dla klienta X",
    "rules": ["Nie wysyłaj maili do klienta bez mojej zgody.", "Cała komunikacja po angielsku."],
    "allowedTools": [{"key": "sharepoint", "name": "SharePoint"}, {"key": "browser", "name": "Przeglądarka"}],
    "unavailableTools": [],
}


class _Klient:
    def __init__(self, polityka=POLITYKA):
        self._polityka = polityka

    def project_policy(self, project_id):
        return self._polityka

    def project_name(self, project_id):
        return "Strona dla klienta X"


class _KlientPadajacy(_Klient):
    def project_policy(self, project_id):
        raise RuntimeError("Projectly nieosiagalne")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    folder = Path(tempfile.mkdtemp())
    original_zbuduj = agentic_prompt.kontekst_firmy.zbuduj
    agentic_prompt.kontekst_firmy.zbuduj = lambda tekst: "--- KONTEKST FIRMY ---"

    try:
        prompt = agentic_prompt.build(TASK, PLAN, folder, client=_Klient())

        checks.append(("Zasady projektu sa w prompcie", "Nie wysyłaj maili do klienta" in prompt))
        checks.append(("Zasady projektu stoja PRZED kontekstem firmy",
                       prompt.index("ZASADY TEGO PROJEKTU") < prompt.index("KONTEKST FIRMY")))
        checks.append(("Zasady projektu stoja PRZED trescia zadania",
                       prompt.index("ZASADY TEGO PROJEKTU") < prompt.index("Zadanie:")))
        checks.append(("Lista dozwolonych narzedzi trafia do promptu",
                       "SharePoint" in prompt and "Przeglądarka" in prompt))
        checks.append(("Prompt zabrania narzedzi spoza listy",
                       "Niczego spoza tej listy nie używaj" in prompt))

        # Error case 1: Projectly nieosiagalne -> prompt powstaje bez bloku zasad.
        prompt_bez = agentic_prompt.build(TASK, PLAN, folder, client=_KlientPadajacy())
        checks.append(("Blad Projectly: prompt powstaje mimo wszystko",
                       "Zadanie:" in prompt_bez and "ZASADY TEGO PROJEKTU" not in prompt_bez))

        # Error case 2: projekt bez zasad i bez narzedzi -> zaden pusty naglowek.
        prompt_pusty = agentic_prompt.build(TASK, PLAN, folder,
                                            client=_Klient({"rules": [], "allowedTools": []}))
        checks.append(("Projekt bez zasad: brak pustego naglowka zasad",
                       "ZASADY TEGO PROJEKTU" not in prompt_pusty))

        # Error case 3: zadanie bez projektu (np. techniczne) nie pyta o polityke.
        prompt_bez_projektu = agentic_prompt.build({"task_id": "T-2", "title": "Cos"}, PLAN, folder,
                                                   client=_Klient())
        checks.append(("Zadanie bez project_id: brak bloku zasad, bez wyjatku",
                       "ZASADY TEGO PROJEKTU" not in prompt_bez_projektu))
    finally:
        agentic_prompt.kontekst_firmy.zbuduj = original_zbuduj

    print("\n--- Wynik testu dymnego agentic_prompt ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'OK  ' if passed else 'BLAD'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedl.")
        sys.exit(1)
    print("\nWszystkie testy przeszly.")


if __name__ == "__main__":
    run()
