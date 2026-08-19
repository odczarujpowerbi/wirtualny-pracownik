"""
Test dymny ui_lock. Sprawdza zajęcie/reentrancję/zwolnienie oraz kradzież
przeterminowanej blokady (wstrzykiwany `now`, żeby TTL był deterministyczny).
Używa tymczasowej ścieżki blokady, żeby nie dotykać żywego runs/.

Użycie:
    python ui_lock_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import ui_lock


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original = ui_lock.LOCK_PATH
    with tempfile.TemporaryDirectory() as tmp:
        ui_lock.LOCK_PATH = Path(tmp) / "ui.lock"

        a = ui_lock.acquire("TASK-A", ttl_seconds=600, now="2026-08-19T10:00:00+00:00")
        checks.append(("acquire A -> ok", a["ok"] and a["held_by"] == "TASK-A"))

        a2 = ui_lock.acquire("TASK-A", now="2026-08-19T10:01:00+00:00")
        checks.append(("acquire A ponownie (reentrant) -> ok", a2["ok"]))

        b = ui_lock.acquire("TASK-B", ttl_seconds=600, now="2026-08-19T10:02:00+00:00")
        checks.append(("acquire B gdy A świeże -> odmowa, held_by A",
                       b["ok"] is False and b["held_by"] == "TASK-A"))

        b_steal = ui_lock.acquire("TASK-B", ttl_seconds=600, now="2026-08-19T10:15:00+00:00")
        checks.append(("acquire B po TTL (13 min) -> kradnie blokadę", b_steal["ok"]))

        checks.append(("current -> TASK-B", ui_lock.current()["task_id"] == "TASK-B"))
        checks.append(("release cudzą (A) -> False", ui_lock.release("TASK-A") is False))
        checks.append(("release własną (B) -> True", ui_lock.release("TASK-B") is True))
        checks.append(("current po zwolnieniu -> None", ui_lock.current() is None))

    ui_lock.LOCK_PATH = original

    print("\n--- Wynik testu dymnego ui_lock ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
