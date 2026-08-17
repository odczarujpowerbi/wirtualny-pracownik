"""
Zapisuje heartbeat.json co wywołanie (PLAN-WDROZENIA.md sekcja 12: co 30-60s
z Harmonogramu zadań Windows). watchdog.py sprawdza jego świeżość.
"""

import json
import platform
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_PATH = Path(__file__).parent / "runs" / "heartbeat.json"


def write_heartbeat(current_task_id=None, extra=None):
    HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "machine": platform.node(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_task_id": current_task_id,
    }
    if extra:
        data.update(extra)
    HEARTBEAT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


if __name__ == "__main__":
    print(write_heartbeat())
