"""
Kesz kontekstu (projekty+etapy z Projectly, wpisy bazy wiedzy) — decyzja
właściciela 30.08.2026: "boty oceniające (bramka) i subagenci ZAWSZE powinny
znać projekt/etap zadania i wiedzę konkretnego agenta wrzuconą w Projectly.
Projekty nie zmieniają się zbyt często, wiedza też nie, więc mogą to
odpytywać rzadko, np. raz dziennie, i sobie aktualizować".

Odświeżany NIE PRZY KAŻDYM zadaniu — raz na DEFAULT_MAX_AGE_HOURS (24h), per
rola (każde konto AI widzi własny zakres wiedzy i projektów). Plik
runs/context_cache<_rola>.json. Fail-soft: błąd sieci przy odświeżaniu ->
zostaje przy STARYM keszu (jeśli jest), nigdy nie wywala cyklu przetwarzania
zadań o dodatkowy kontekst.

Wołający (runner_loop.py) odświeża RAZ na cykl (`refresh_if_stale`, tanio gdy
świeży — sam odczyt pliku) i przekazuje gotowy słownik dalej do
bot_gustaw_bramka.run_gate / bot_content_check.judge/review / agentic_worker.run
— te moduły NIE wołają Projectly same, tylko czytają już pobrany kesz.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

CACHE_DIR = Path(__file__).parent / "runs"
DEFAULT_MAX_AGE_HOURS = 24
KNOWLEDGE_DIGEST_LIMIT = 5
KNOWLEDGE_DIGEST_MAX_CHARS = 2000

EMPTY_CACHE = {"fetched_at": None, "projects": [], "knowledge": []}


def _cache_path(role=None):
    suffix = "" if not role or role == "dev" else f"_{role}"
    return CACHE_DIR / f"context_cache{suffix}.json"


def _load(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return None


def _save(data, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_stale(cache, max_age_hours):
    if not cache or not cache.get("fetched_at"):
        return True
    try:
        wiek = datetime.now(timezone.utc) - datetime.fromisoformat(cache["fetched_at"])
    except ValueError:
        return True
    return wiek >= timedelta(hours=max_age_hours)


def refresh_if_stale(client, role=None, max_age_hours=DEFAULT_MAX_AGE_HOURS, force=False):
    """Odświeża kesz (projekty+etapy, wpisy bazy wiedzy), gdy stary/brak.
    Fail-soft: błąd sieci/Projectly -> zostaje przy STARYM keszu (jeśli jest),
    inaczej EMPTY_CACHE — nigdy nie rzuca, nigdy nie blokuje wywołującego.
    Zwraca kesz (świeży albo stary/pusty, zależnie co się udało)."""
    path = _cache_path(role)
    cache = _load(path)
    if not force and not _is_stale(cache, max_age_hours):
        return cache
    try:
        projekty = client.list_projects_with_stages() if hasattr(client, "list_projects_with_stages") else []
        wiedza = client.get_knowledge_base() if hasattr(client, "get_knowledge_base") else {"entries": []}
        nowy = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "projects": projekty or [],
            "knowledge": wiedza.get("entries") or [],
        }
        _save(nowy, path)
        return nowy
    except Exception as exc:  # noqa: BLE001 — kesz jest dodatkiem, błąd nie może ubić cyklu
        print(f"[context_cache] Odświeżenie nie powiodło się ({role}): {exc}")
        return cache or dict(EMPTY_CACHE)


def project_and_stage_text(cache, project_id, stage_id=None):
    """'Projekt: X, Etap: Y' do promptu — pusty string, gdy projekt nieznany
    (fail-soft, nie ma czego pokazać)."""
    for p in (cache or {}).get("projects", []):
        if p.get("id") == project_id:
            linia = f"Projekt: {p.get('name')}"
            if stage_id:
                etap = next((s.get("name") for s in (p.get("stages") or []) if s.get("id") == stage_id), None)
                if etap:
                    linia += f", Etap: {etap}"
            return linia
    return ""


def knowledge_digest_text(cache, limit=KNOWLEDGE_DIGEST_LIMIT, max_chars=KNOWLEDGE_DIGEST_MAX_CHARS):
    """Skrócony digest NAJNOWSZYCH wpisów bazy wiedzy (do promptu) — pusty
    string, gdy kesz pusty/brak wpisów."""
    wpisy = sorted((cache or {}).get("knowledge") or [], key=lambda w: w.get("updatedAt") or "", reverse=True)
    wpisy = wpisy[:limit]
    if not wpisy:
        return ""
    linie = [f"### {w.get('title') or '(bez tytułu)'}\n{(w.get('content') or '')[:400]}" for w in wpisy]
    return "\n\n".join(linie)[:max_chars]


def context_block(cache, task):
    """Blok tekstu do promptu: projekt+etap zadania + digest wiedzy — pomija
    części, których nie da się zbudować (fail-soft), pusty string gdy nic."""
    czesci = [
        blok for blok in (
            project_and_stage_text(cache, task.get("project_id"), task.get("stage_id")),
            knowledge_digest_text(cache),
        ) if blok
    ]
    return "\n\n".join(czesci)
