"""
Test dymny samo-zamykania bota (decyzja właściciela 01.09.2026): proces
job_scheduler.py ma się SAM zakończyć, gdy jego zadanie sterujące w Projectly
jest wyłączone I nie ma nic w toku. Świadomie bez limitu czasowego — zadanie
może trwać godzinami, więc kryterium jest sprawdzalne ("czy jakiś job jeszcze
pracuje"), a nie odliczane.

Sprawdza jedno i drugie:
  - prace_w_toku(): co liczy się jako praca w toku (wątek żywy, ale uznany za
    zawieszony, NIE blokuje zamknięcia — inaczej bot nie zamknąłby się nigdy),
  - run_scheduler(): realnie WYCHODZI z pętli, a nie kręci się dalej.

Izoluje blokadę plikową (scheduler_lock.LOCK_PATH), katalog flag (control.RUNS_DIR)
i podmienia remote_control.sync atrapą — zero sieci, zero wpływu na żywy proces
bota na tej maszynie.

Użycie:
    python job_scheduler_self_exit_smoke_test.py
"""

import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import control
import job_scheduler
import kill_switch
import remote_control
import scheduler_lock

TERAZ = datetime(2026, 9, 1, 18, 0, 0, tzinfo=timezone.utc)


def _watek_ktory_zyje(stop_event):
    t = threading.Thread(target=stop_event.wait, daemon=True)
    t.start()
    return t


def _watek_zakonczony():
    t = threading.Thread(target=lambda: None, daemon=True)
    t.start()
    t.join()
    return t


def _checki_prace_w_toku():
    checks = []
    stop = threading.Event()
    zywy = _watek_ktory_zyje(stop)
    martwy = _watek_zakonczony()
    try:
        aktywne = job_scheduler.prace_w_toku(
            {"runner_loop": zywy}, {"runner_loop": TERAZ - timedelta(seconds=30)},
            {"runner_loop": 1800}, TERAZ)
        checks.append(("prace_w_toku: żywy wątek w limicie -> praca W TOKU (nie zamykamy)",
                       aktywne == ["runner_loop"]))

        aktywne = job_scheduler.prace_w_toku(
            {"runner_loop": martwy}, {"runner_loop": TERAZ - timedelta(seconds=30)},
            {"runner_loop": 1800}, TERAZ)
        checks.append(("prace_w_toku: wątek zakończony -> biurko PUSTE", aktywne == []))

        # Wątek żywy, ale watchdog uznał go za zawieszony: scheduler już go
        # osierocił, więc czekanie na niego nie skończyłoby się NIGDY.
        aktywne = job_scheduler.prace_w_toku(
            {"runner_loop": zywy}, {"runner_loop": TERAZ - timedelta(seconds=5000)},
            {"runner_loop": 1800}, TERAZ)
        checks.append(("prace_w_toku: wątek zawieszony (poza limitem) NIE blokuje zamknięcia",
                       aktywne == []))

        # Brak zapisanego limitu -> limit domyślny, nie wyjątek.
        aktywne = job_scheduler.prace_w_toku(
            {"runner_loop": zywy}, {"runner_loop": TERAZ - timedelta(seconds=30)}, {}, TERAZ)
        checks.append(("prace_w_toku: brak wpisu o limicie -> używa domyślnego, bez wyjątku",
                       aktywne == ["runner_loop"]))
    finally:
        stop.set()
    return checks


def _uruchom_scheduler_z_timeoutem(schedule_path, timeout=15):
    """run_scheduler w osobnym wątku. Zwraca True, gdy sam wyszedł w czasie —
    czyli dokładnie to, co ma robić bot wyłączony i bez pracy w toku."""
    wynik = {"wyszedl": False}

    def _cel():
        job_scheduler.run_scheduler(tick_seconds=1, schedule_path=schedule_path)
        wynik["wyszedl"] = True

    t = threading.Thread(target=_cel, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return wynik["wyszedl"]


def _checki_run_scheduler(tmp):
    """Realna pętla, ale w piaskownicy: własna blokada, własny katalog flag,
    sync podmieniony (zero sieci)."""
    checks = []
    schedule_path = tmp / "schedule.yaml"
    schedule_path.write_text(
        "jobs:\n"
        "  - name: nic_nie_robi\n"
        "    module: job_scheduler\n"
        "    function: print_status\n"
        "    interval_seconds: 99999\n"
        "    enabled: false\n",
        encoding="utf-8")

    control.pause(reason="Wstrzymany z Projectly (test dymny).", role=job_scheduler.CURRENT_ROLE)
    wyszedl = _uruchom_scheduler_z_timeoutem(schedule_path)
    checks.append(("run_scheduler: WYŁĄCZONY i puste biurko -> proces sam się zamyka", wyszedl))
    checks.append(("run_scheduler: po samo-zamknięciu blokada jest ZWOLNIONA "
                   "(nadzorca zobaczy 'nie działa')",
                   scheduler_lock.running_pid(job_scheduler.CURRENT_ROLE) is None))

    control.resume(role=job_scheduler.CURRENT_ROLE)
    wyszedl_wlaczony = _uruchom_scheduler_z_timeoutem(schedule_path, timeout=4)
    checks.append(("run_scheduler: WŁĄCZONY -> pętla działa dalej, NIE zamyka się",
                   wyszedl_wlaczony is False))
    return checks


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    original_runs_dir = control.RUNS_DIR
    original_lock_path = scheduler_lock.LOCK_PATH
    original_stop_flag = kill_switch.STOP_FLAG_PATH
    original_sync = remote_control.sync
    original_state_path = job_scheduler.STATUS_PATH

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        control.RUNS_DIR = tmp
        scheduler_lock.LOCK_PATH = tmp / "job_scheduler.lock"
        kill_switch.STOP_FLAG_PATH = tmp / "STOP.flag"
        job_scheduler.STATUS_PATH = tmp / "scheduler_status.json"
        remote_control.sync = lambda **kwargs: None  # zero sieci
        try:
            checks = _checki_prace_w_toku() + _checki_run_scheduler(tmp)
        finally:
            control.RUNS_DIR = original_runs_dir
            scheduler_lock.LOCK_PATH = original_lock_path
            kill_switch.STOP_FLAG_PATH = original_stop_flag
            job_scheduler.STATUS_PATH = original_state_path
            remote_control.sync = original_sync

    print("\n--- Wynik testu dymnego samo-zamykania bota ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    return all_passed


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
