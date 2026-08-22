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

Zapis do bazy wiedzy: WYMAGA narzedzia MCP do zapisu. Na dzien napisania
(22.08.2026) produkcja Projectly NIE MA takiego narzedzia - tylko get_knowledge/
get_knowledge_base/get_knowledge_attachment (odczyt). Nazwa/schema przyszlego
narzedzia zapisu jest NIEZNANA, wiec zamiast zgadywac ja na sztywno w kodzie
(ryzyko cichego, blednego wywolania co godzine), czytamy ja z
config/projectly.yaml -> knowledge_digest.mcp_tool. Puste/None = skrypt
buduje i loguje tresc digestu, ale NIE probuje zapisac (fail-soft) - ustaw
te wartosc, jak tylko nazwa narzedzia bedzie potwierdzona, bez zmiany kodu.
"""

from datetime import datetime, timezone
from pathlib import Path

from mcp_client import MCPError
from projectly_client import ProjectlyClient, _load_config

AGENTS_DIR = Path(__file__).parent / "secrets" / "agents"
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


def _publish_to_knowledge_base(client, role, title, content, cfg=None):
    """Zapisuje wpis bazy wiedzy w zakresie WLASNEGO konta (tozsamosc = token,
    ten sam wzorzec co post_agent_status). Nazwa narzedzia MCP z configu - patrz
    docstring modulu (cfg wstrzykiwalny - testowalnosc, domyslnie config/projectly.yaml).
    Brak configu/blad MCP = tylko log, nie wywala przebiegu."""
    cfg = (cfg if cfg is not None else _load_config()).get("knowledge_digest", {})
    tool_name = cfg.get("mcp_tool")
    if not tool_name:
        print(
            f"[knowledge_digest] [{role}] narzędzie MCP zapisu bazy wiedzy jeszcze "
            f"nieskonfigurowane (config/projectly.yaml -> knowledge_digest.mcp_tool) "
            f"- treść zbudowana, ale NIE zapisana:\n{content}\n"
        )
        return False
    try:
        client._mcp.call_tool(tool_name, {"title": title, "contentMarkdown": content})
        return True
    except MCPError as exc:
        print(f"[knowledge_digest] [{role}] zapis do bazy wiedzy nie powiódł się: {exc}")
        return False


def run_knowledge_digest(roles=None, agents_dir=AGENTS_DIR):
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
        ok = _publish_to_knowledge_base(client, role, DEFAULT_TITLE, text)
        results[role] = "opublikowano" if ok else "narzedzie_zapisu_niedostepne"
    return results


if __name__ == "__main__":
    print(run_knowledge_digest())
