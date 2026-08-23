"""
Cogodzinny digest "ostatnia aktywnosc" per konto AI (dev/marketing/zarzad),
publikowany do bazy wiedzy Projectly w zakresie WLASNEGO konta bota (zlecone
22.08.2026). Kazde konto ma wlasny token w app/secrets/agents/<rola>/.env
(patrz env_bootstrap.py) - ten skrypt, w odroznieniu od reszty runnera (ktory
dziala jako JEDNA rola tej maszyny), laduje WSZYSTKIE trzy naraz, bo aktualizuje
wszystkie konta w jednym przebiegu, niezaleznie od tego, ktora rola jest
skonfigurowana w config/role.json.

Zrodlo danych: get_week_report (MCP) - to samo narzedzie, ktorego
digest_generator.py/weekly_team_report.py uzywaja do cotygodniowych podsumowan;
tu wolane co godzine i per-konto (kazdy bot widzi SWOJ wiersz w perPerson +
ogolny kontekst organizacji), zamiast raz w tygodniu i zbiorczo do komentarza.

Zapis do bazy wiedzy: MCP create_knowledge/update_knowledge (potwierdzone na
produkcji 22.08.2026). Każde konto pisze WYŁĄCZNIE do własnego zakresu
(scope="self", domyślne) - jeden, stały wpis per rola, NADPISYWANY co przebieg
(update_knowledge), nie nowy wpis co godzinę - id utworzonego wpisu trzymamy
lokalnie w runs/knowledge_entry_ids.json (nie ma narzędzia do usuwania wpisów,
więc raz utworzony zostaje - stąd upsert po id, nie tworzenie na ślepo).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from mcp_client import MCPError
from projectly_client import ProjectlyClient

AGENTS_DIR = Path(__file__).parent / "secrets" / "agents"
ENTRY_IDS_PATH = Path(__file__).parent / "runs" / "knowledge_entry_ids.json"
ROLES = ["dev", "marketing", "zarzad"]
BOT_DISPLAY_NAME = {"dev": "AI - Dev", "marketing": "AI - Marketing", "zarzad": "AI - Zarząd"}
DEFAULT_TITLE = "Ostatnia aktywność (automatyczny digest)"


def _load_agent_env(role, agents_dir=AGENTS_DIR):
    """Wczytuje PROJECTLY_API_KEY/PROJECTLY_BASE_URL z secrets/agents/<rola>/.env.
    Zwraca None, gdy plik nie istnieje albo jest niekompletny (rola jeszcze bez
    tokenu) - fail-soft, wywolujacy pomija te role zamiast wywalac caly przebieg."""
    path = Path(agents_dir) / role / ".env"
    if not path.exists():
        return None
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    if not env.get("PROJECTLY_API_KEY") or not env.get("PROJECTLY_BASE_URL"):
        return None
    return env


def _client_for_role(role, agents_dir=AGENTS_DIR):
    env = _load_agent_env(role, agents_dir)
    if not env:
        return None
    return ProjectlyClient(api_key=env["PROJECTLY_API_KEY"], base_url=env["PROJECTLY_BASE_URL"])


def build_digest_text(client, role, now=None):
    """Buduje tresc digestu z get_week_report(weekOffset=0). Rola "zarzad"
    dostaje dodatkowo rozbicie po WSZYSTKICH osobach/botach (nadzor calej
    organizacji), pozostale role tylko wlasny wiersz + ogolny kontekst."""
    now = now or datetime.now(timezone.utc)
    bot_name = BOT_DISPLAY_NAME.get(role, role)
    report = client.get_week_report(week_offset=0)

    rng = report.get("range") or {}
    summary = report.get("summary") or {}
    per_person = report.get("perPerson") or []
    completed = report.get("completed") or []

    own = next((p for p in per_person if p.get("name") == bot_name), None)
    own_completed = [c for c in completed if bot_name in (c.get("assignees") or [])][:5]

    lines = [
        f"# {bot_name} — ostatnia aktywność",
        f"_Automatyczny digest, tydzień {rng.get('from', '?')} – {rng.get('to', '?')}, "
        f"wygenerowano {now.isoformat()}_",
        "",
        "## Twoje liczby w tym tygodniu",
    ]
    if own:
        lines.append(
            f"- Wykonane: {own.get('completedCount', 0)} · w toku: {own.get('inProgressCount', 0)} "
            f"· utknięte (bez ruchu): {own.get('stuckCount', 0)}"
        )
    else:
        lines.append("- Brak zadań przypisanych w tym tygodniu.")

    lines += [
        "",
        "## Cała organizacja (kontekst)",
        f"- Wykonane łącznie: {summary.get('completedCount', 0)} · aktywne blokery: "
        f"{summary.get('activeBlockerCount', 0)} · utknięte: {summary.get('stuckCount', 0)}",
    ]

    if role == "zarzad" and per_person:
        lines += ["", "## Rozbicie po osobach i botach"]
        for p in per_person:
            lines.append(
                f"- {p.get('name')}: wykonane {p.get('completedCount', 0)}, w toku "
                f"{p.get('inProgressCount', 0)}, utknięte {p.get('stuckCount', 0)}"
            )

    if own_completed:
        lines += ["", "## Przykładowe wykonane zadania"]
        for c in own_completed:
            lines.append(f"- {c.get('title')} ({c.get('project')})")

    return "\n".join(lines)


def _load_entry_ids(path=ENTRY_IDS_PATH):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
    return {}


def _save_entry_ids(entry_ids, path=ENTRY_IDS_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entry_ids, ensure_ascii=False, indent=2), encoding="utf-8")


def _publish_to_knowledge_base(client, role, title, content, entry_ids_path=ENTRY_IDS_PATH):
    """Upsert wpisu bazy wiedzy w zakresie WŁASNEGO konta (scope="self",
    tożsamość = token — jak post_agent_status): pierwszy przebieg tworzy
    (create_knowledge), kolejne NADPISUJĄ ten sam wpis (update_knowledge) po
    id zapamiętanym w entry_ids_path — bez tego co godzinę powstawałby nowy
    wpis, a nie ma narzędzia MCP do usuwania. Błąd MCP = tylko log, nie
    wywala przebiegu (fail-soft, jak publish_status)."""
    entry_ids = _load_entry_ids(entry_ids_path)
    existing_id = entry_ids.get(role)
    try:
        if existing_id:
            client.update_knowledge(existing_id, title=title, content=content)
        else:
            result = client.create_knowledge(title, content, scope="self")
            new_id = result.get("id") if isinstance(result, dict) else None
            if new_id:
                entry_ids[role] = new_id
                _save_entry_ids(entry_ids, entry_ids_path)
        return True
    except MCPError as exc:
        print(f"[knowledge_digest] [{role}] zapis do bazy wiedzy nie powiódł się: {exc}")
        return False


def run_knowledge_digest(roles=None, agents_dir=AGENTS_DIR, entry_ids_path=ENTRY_IDS_PATH):
    """Bezargumentowe dla job_scheduler.py (config/schedule.yaml, job
    'knowledge_digest_publisher', co godzinę). Zwraca {rola: wynik} - dla
    dashboardu (zakładka Skrypty) i testów."""
    roles = roles or ROLES
    results = {}
    for role in roles:
        client = _client_for_role(role, agents_dir)
        if not client:
            print(f"[knowledge_digest] [{role}] brak tokenu w secrets/agents/{role}/.env - pomijam.")
            results[role] = "brak_tokenu"
            continue
        try:
            text = build_digest_text(client, role)
        except MCPError as exc:
            print(f"[knowledge_digest] [{role}] błąd pobierania danych (get_week_report): {exc}")
            results[role] = "blad_odczytu"
            continue
        ok = _publish_to_knowledge_base(client, role, DEFAULT_TITLE, text, entry_ids_path=entry_ids_path)
        results[role] = "opublikowano" if ok else "zapis_nieudany"
    return results


if __name__ == "__main__":
    print(run_knowledge_digest())
