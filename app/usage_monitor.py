"""
Kontrola zuzycia Claude i estymacja "ile zadan jeszcze" (na prosbe wlasciciela:
agent ma miec kontrole nad limitami widocznymi w statuslinii terminala).

Zrodlo danych: ~/.claude/powerline/usage/today.json - ten sam surowy log zuzycia,
z ktorego statuslinia (claude-powerline) liczy blok 5h / dzis. Kazdy rekord:
{timestamp, usage:{input/output/cache...}, costUSD, model}.

Co liczymy:
- block_5h_usd / today_usd : realny koszt w oknie 5h i dzis (jak w statuslinii),
- estimate_remaining_tasks : ILE zadan jeszcze zmiescimy w budzecie okna 5h,
  na podstawie sredniego kosztu zadania (z wlasnego dziennika decyzji state.db,
  a gdy brak danych - z ostatnich wywolan).

UCZCIWIE: twardy limit subskrypcji (dokladny sufit okna 5h/tygodnia) NIE jest
dostepny programowo - statuslinia pokazuje %, ale liczba progu nie jest w tym
pliku. Dlatego estymacja jest wzgledem BUDZETU, ktory ustawiasz (block_budget_usd),
nie wobec ukrytego limitu Anthropic. To swiadome, jawne zalozenie.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

USAGE_PATH = Path.home() / ".claude" / "powerline" / "usage" / "today.json"

# Budzet okna 5h w USD - punkt odniesienia estymacji. Ustawiany przez wlasciciela
# (nie jest to ukryty limit Anthropic, tylko Twoj prog ostroznosci). Domyslnie
# zachowawczo; docelowo do config/usage_budget.yaml.
DEFAULT_BLOCK_BUDGET_USD = 40.0
BLOCK_HOURS = 5


def _now():
    return datetime.now(timezone.utc)


def load_records(path=USAGE_PATH):
    """Lista rekordow zuzycia. Pusta lista, gdy pliku brak (np. przed pierwsza
    sesja Claude na maszynie) - nie wywalamy sie, degradujemy lagodnie."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return raw.get("data", []) if isinstance(raw, dict) else (raw or [])


def _parse_ts(rec):
    ts = rec.get("timestamp", "")
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _sum_cost(records):
    return round(sum(r.get("costUSD", 0) or 0 for r in records), 4)


def window_usage(records, hours=BLOCK_HOURS, now=None):
    """Koszt i liczba wywolan w ostatnich `hours` godzinach."""
    now = now or _now()
    cutoff = now - timedelta(hours=hours)
    inside = [r for r in records if (_parse_ts(r) or now) >= cutoff]
    return {"cost_usd": _sum_cost(inside), "calls": len(inside)}


def today_usage(records):
    """Caly plik to 'dzis' wg claude-powerline - sumujemy wszystko."""
    return {"cost_usd": _sum_cost(records), "calls": len(records)}


def _avg_task_cost(default_from_records):
    """Sredni koszt JEDNEGO zadania. Preferujemy wlasny dziennik decyzji
    (state.db, wpisy execution z cost_usd per task) - to realny koszt zadania
    agenta. Fallback: sredni koszt wywolania z today.json (grubsze przyblizenie)."""
    try:
        import state_store
        conn = state_store.get_connection()
        rows = conn.execute(
            "SELECT cost_usd FROM events WHERE event_type='execution' AND cost_usd IS NOT NULL AND cost_usd > 0"
        ).fetchall()
        conn.close()
        costs = [r[0] for r in rows]
        if costs:
            return sum(costs) / len(costs), "dziennik decyzji (execution)"
    except Exception:  # noqa: BLE001 - brak bazy/kolumny nie moze wywrocic monitora
        pass
    return default_from_records, "srednia z ostatnich wywolan Claude"


def summary(path=USAGE_PATH, block_budget_usd=DEFAULT_BLOCK_BUDGET_USD, now=None):
    """Zbiorczy widok dla dashboardu i eskalacji: zuzycie 5h/dzis + estymacja
    ile zadan jeszcze zmiescimy w budzecie okna 5h."""
    records = load_records(path)
    if not records:
        return {"available": False,
                "reason": "Brak danych zuzycia (~/.claude/powerline/usage/today.json) - jeszcze zadnej sesji Claude."}

    block = window_usage(records, hours=BLOCK_HOURS, now=now)
    today = today_usage(records)

    avg_call = (today["cost_usd"] / today["calls"]) if today["calls"] else 0.0
    avg_task, basis = _avg_task_cost(avg_call)

    remaining_budget = max(0.0, block_budget_usd - block["cost_usd"])
    est_tasks = int(remaining_budget / avg_task) if avg_task > 0 else None

    return {
        "available": True,
        "block_5h_usd": block["cost_usd"],
        "block_5h_calls": block["calls"],
        "today_usd": today["cost_usd"],
        "today_calls": today["calls"],
        "block_budget_usd": block_budget_usd,
        "block_budget_used_pct": round(100 * block["cost_usd"] / block_budget_usd, 1) if block_budget_usd else None,
        "avg_task_cost_usd": round(avg_task, 4),
        "avg_task_cost_basis": basis,
        "estimated_tasks_remaining": est_tasks,
    }


if __name__ == "__main__":
    import sys
    print(json.dumps(summary(), ensure_ascii=False, indent=2))
    if "--brief" in sys.argv:
        s = summary()
        if s["available"]:
            print(f"\n5h: ${s['block_5h_usd']} / ${s['block_budget_usd']} "
                  f"({s['block_budget_used_pct']}%) | dzis: ${s['today_usd']} | "
                  f"szac. zadan jeszcze: {s['estimated_tasks_remaining']}")
