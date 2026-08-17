"""
Wykrywa brak heartbeat i sygnalizuje zawieszenie runnera
(PLAN-WDROZENIA.md sekcja 12: co 1-2 min, niezależny proces).
Na razie: alarm na stdout + plik ALERT.flag. Docelowo: eskalacja do Projectly
(escalate_to_human.py, PLAN-WDROZENIA.md sekcja 4).
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HEARTBEAT_PATH = Path(__file__).parent / "runs" / "heartbeat.json"
ALERT_PATH = Path(__file__).parent / "runs" / "ALERT.flag"
STALE_AFTER_SECONDS = 120


def check():
    if not HEARTBEAT_PATH.exists():
        return _alert("Brak pliku heartbeat.json — runner prawdopodobnie nigdy nie wystartował.")

    data = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
    last_beat = datetime.fromisoformat(data["updated_at"])
    now = datetime.now(timezone.utc)
    age_seconds = (now - last_beat).total_seconds()

    if age_seconds > STALE_AFTER_SECONDS:
        return _alert(f"Heartbeat nieaktualny od {age_seconds:.0f}s (limit {STALE_AFTER_SECONDS}s).")

    ALERT_PATH.unlink(missing_ok=True)
    return {"status": "ok", "age_seconds": age_seconds}


def _alert(message):
    ALERT_PATH.parent.mkdir(parents=True, exist_ok=True)
    ALERT_PATH.write_text(message, encoding="utf-8")
    return {"status": "alert", "message": message}


if __name__ == "__main__":
    result = check()
    print(result)
    sys.exit(0 if result["status"] == "ok" else 1)
