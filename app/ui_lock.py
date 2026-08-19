"""
Blokada sesji UI — realizacja zasady "jedno aktywne okno na zadanie" (rekomendacja
architekta + coding-rules sekcja 13: operacje wzajemnie wykluczające się blokują
następną). Praca na plikach może iść równolegle, ale STEROWANIE EKRANEM (fokus,
klik, zrzut konkretnego okna) musi być sekwencyjne — dwa zadania walczące o fokus
to gwarantowany błąd.

Prosty plik-mutex w runs/ (runtime, w .gitignore). Kradnie blokadę starszą niż
TTL (zabezpieczenie przed zakleszczeniem, gdy poprzednie zadanie padło bez
zwolnienia). `now` wstrzykiwalne w testach (ISO 8601), żeby TTL dało się sprawdzić
deterministycznie.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOCK_PATH = Path(__file__).parent / "runs" / "ui_session.lock"
DEFAULT_TTL_SECONDS = 600


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _read():
    if not LOCK_PATH.exists():
        return None
    try:
        return json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _write(record):
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")


def _age_seconds(record, now_iso):
    try:
        acquired = datetime.fromisoformat(record["acquired_at"])
        return (datetime.fromisoformat(now_iso) - acquired).total_seconds()
    except (KeyError, ValueError):
        return float("inf")  # nieczytelny znacznik = traktuj jak przeterminowany


def current():
    """Kto trzyma blokadę (albo None)."""
    return _read()


def acquire(task_id, ttl_seconds=DEFAULT_TTL_SECONDS, now=None):
    """Próbuje zająć blokadę UI dla task_id. Zwraca {ok, held_by, detail}.
    Reentrant: to samo zadanie może zająć ponownie. Kradnie blokadę starszą niż
    ttl_seconds (poprzednie zadanie padło bez release)."""
    now = now or _now_iso()
    held = _read()
    if held is not None and held.get("task_id") not in (None, task_id):
        if _age_seconds(held, now) <= ttl_seconds:
            return {"ok": False, "held_by": held.get("task_id"),
                    "detail": f"UI zajęte przez {held.get('task_id')} od {held.get('acquired_at')}."}
        # blokada przeterminowana — przejmujemy
    _write({"task_id": task_id, "acquired_at": now, "pid": os.getpid()})
    return {"ok": True, "held_by": task_id, "detail": "Blokada UI zajęta."}


def release(task_id):
    """Zwalnia blokadę, jeśli należy do task_id. Zwraca True, gdy zwolniono."""
    held = _read()
    if held is None:
        return False
    if held.get("task_id") != task_id:
        return False
    try:
        LOCK_PATH.unlink()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    print(acquire("DEMO-1"))
    print(current())
    print(release("DEMO-1"))
