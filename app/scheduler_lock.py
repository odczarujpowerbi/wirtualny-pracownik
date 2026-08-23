"""
Blokada jednej żywej instancji job_scheduler.py naraz — realizacja zasady
"jak kliknę dwa razy, mam tylko jednego agenta" (żądanie użytkownika
24.08.2026). Dwa procesy job_scheduler.py naraz to POTWIERDZONY scenariusz
uszkodzenia na tej maszynie: każdy pisze do tych samych plików stanu w
runs/ (scheduler_status.json, run_history.jsonl) bez wiedzy o drugim.

Plik-mutex w runs/ (poza gitem), wzorowany na ui_lock.py, ale z INNYM
testem żywotności: tam sesja UI ma sens tylko chwilę, więc wystarczał wiek
wpisu (TTL). job_scheduler.py ma żyć tygodniami — TTL by go ubił niezależnie
od tego, czy faktycznie działa. Test żywotności to więc realne sprawdzenie
procesu (psutil.pid_exists), nie wiek pliku. Dodatkowo porównujemy cmdline,
żeby PID odzyskany przez system po restarcie maszyny (inny proces, ten sam
numer) nie fałszywie wyglądał na "scheduler wciąż żyje".
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path

LOCK_PATH = Path(__file__).parent / "runs" / "job_scheduler.lock"


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


def _is_alive(record):
    """Prawdziwy test żywotności procesu, nie wiek pliku."""
    pid = record.get("pid")
    if not pid:
        return False
    try:
        import psutil
    except ImportError:
        return True  # bez psutil nie potwierdzimy śmierci -> bezpieczniej uznać za żywy
    if not psutil.pid_exists(pid):
        return False
    try:
        proc = psutil.Process(pid)
        cmdline = " ".join(proc.cmdline()).lower()
    except psutil.Error:
        return False
    # PID mógł zostać oddany innemu procesowi (np. po restarcie maszyny) —
    # potwierdzamy, że to wciąż job_scheduler.py, nie zgadujemy po samym PID.
    return "job_scheduler" in cmdline


def acquire(pid=None):
    """Próbuje zająć blokadę jedynej żywej instancji. Zwraca {ok, detail}.
    Blokadę martwego procesu (crash bez czyszczenia) przejmuje automatycznie."""
    held = _read()
    if held is not None and _is_alive(held):
        return {"ok": False, "detail": (
            f"job_scheduler.py już działa (PID {held.get('pid')}, "
            f"od {held.get('started_at')}) — nie startuję drugiej instancji."
        )}
    _write({"pid": pid if pid is not None else os.getpid(), "started_at": _now_iso()})
    return {"ok": True, "detail": "Blokada zajęta."}


def release(pid=None):
    """Zwalnia blokadę, jeśli należy do TEGO procesu (własny PID) — nie kradnie
    blokady innej, żywej instancji przez przypadkowy wyścig."""
    pid = pid if pid is not None else os.getpid()
    held = _read()
    if held is None or held.get("pid") != pid:
        return False
    try:
        LOCK_PATH.unlink()
        return True
    except OSError:
        return False


if __name__ == "__main__":
    print(acquire())
    print(_read())
    print(release())
