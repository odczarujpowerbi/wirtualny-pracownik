"""
Utrzymuje jeden, stały, nadpisywany wpis "status na żywo" per bot-rola w
Projectly (PLAN-WDROZENIA.md sekcja 2 — moduł analizy pracy w toku, nie
tylko zakończonych zadań). Harmonogram: co 1-2 min (config/schedule.yaml).

MCP: client.publish_status -> create/update_documentation (strona statusu per
rola, nadpisywana). Cel/tytuł strony w config/projectly.yaml (live_status).
Kolejki liczone LOKALNIE ze state_store (stan tej maszyny), nie z Projectly.
"""

import platform
from datetime import datetime, timezone
from pathlib import Path

import cost_tracker
import state_store
import watchdog

HEARTBEAT_PATH = Path(__file__).parent / "runs" / "heartbeat.json"


def build_status(role="dev"):
    watchdog_result = watchdog.check()
    cost = cost_tracker.check_daily_limit()

    queued = len(state_store.list_tasks(status="queued"))
    needs_approval = len(state_store.list_tasks(status="needs_approval"))

    current_task_id = None
    if HEARTBEAT_PATH.exists():
        import json

        hb = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        current_task_id = hb.get("current_task_id")

    return {
        "role": role,
        "machine": platform.node(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_task_id": current_task_id,
        "queue_depth": queued,
        "needs_approval_count": needs_approval,
        "cost_today_usd": round(cost["total"], 4),
        "cost_limit_usd": cost["limit"],
        "health": "ok" if watchdog_result["status"] == "ok" else "alert",
    }


def publish(client, role="dev"):
    status = build_status(role)
    client.publish_status(role, status)
    return status


if __name__ == "__main__":
    from projectly_client import get_client

    print(publish(get_client()))
