"""
Sumuje koszt AI per zadanie/dzień, alarmuje po przekroczeniu limitu
(PLAN-WDROZENIA.md sekcja 3 — kalibracja kosztu jest tu, gdzie się to mierzy;
sekcja 17 — kill switch jako ostatnia linia, gdy limit globalny zostanie
przekroczony)."""

from datetime import datetime, timezone
from pathlib import Path

import state_store

DAILY_LIMIT_PATH = Path(__file__).parent / "config" / "daily_cost_limit_usd.txt"
DEFAULT_DAILY_LIMIT_USD = 20.0  # zgodnie z limitem pilotażowym z dokumentacji bazowej


def _daily_limit():
    if DAILY_LIMIT_PATH.exists():
        return float(DAILY_LIMIT_PATH.read_text(encoding="utf-8").strip())
    return DEFAULT_DAILY_LIMIT_USD


def record_cost(task_id, cost_usd, model="unknown"):
    now = datetime.now(timezone.utc).isoformat()
    state_store.record_event(task_id, "cost", f"{cost_usd:.4f} USD ({model})", now)


def today_total():
    """Sumuje koszt z dzisiejszych zdarzeń typu 'cost' we wszystkich zadaniach."""
    conn = state_store.get_connection()
    today_prefix = datetime.now(timezone.utc).date().isoformat()
    rows = conn.execute(
        "SELECT detail FROM events WHERE event_type = 'cost' AND created_at LIKE ?",
        (f"{today_prefix}%",),
    ).fetchall()
    conn.close()

    total = 0.0
    for (detail,) in rows:
        try:
            total += float(detail.split(" USD")[0])
        except (ValueError, IndexError):
            continue
    return total


def check_daily_limit():
    total = today_total()
    limit = _daily_limit()
    if total > limit:
        return {"over_limit": True, "total": total, "limit": limit}
    return {"over_limit": False, "total": total, "limit": limit}


if __name__ == "__main__":
    record_cost("PRJ-TEST", 0.15, model="claude")
    print(check_daily_limit())
