"""
Test dymny: run_scheduler() woła remote_control.sync() PRIORYTETOWO, na samym
początku KAŻDEGO ticku pętli — PRZED sprawdzeniem control.is_paused() (bo
inaczej, gdyby sync() był POD tym warunkiem, bot wstrzymany przez Projectly
nigdy by nie zobaczył zmiany statusu z powrotem na "wznów" — patrz komentarz
w job_scheduler.py przy tym wywołaniu).

Zero realnej pętli w nieskończoność: time.sleep podmieniony atrapą, która po
zadanej liczbie ticków przerywa pętlę wyjątkiem (jedyny sposób, żeby
deterministycznie "wyjść" z `while True` bez modyfikowania run_scheduler()).
scheduler_lock.acquire/release podmienione, żeby test nie dotykał
prawdziwego pliku blokady tej maszyny.

prace_w_toku() podmienione tak, żeby udawać ZADANIE W TOKU (01.09.2026): od tej
daty bot wyłączony i z pustym biurkiem SAM ZAMYKA proces, więc bez tego pętla
kończyłaby się po pierwszym ticku i nie dałoby się sprawdzić kolejności wywołań
na kolejnych. Samo zamykanie ma własny test: job_scheduler_self_exit_smoke_test.py.

Użycie:
    python job_scheduler_remote_control_priority_smoke_test.py
"""

import sys

import job_scheduler
import remote_control


class _StopPetli(Exception):
    pass


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_acquire = job_scheduler.scheduler_lock.acquire
    original_release = job_scheduler.scheduler_lock.release
    original_sync = remote_control.sync
    original_is_paused = job_scheduler.control.is_paused
    original_kill_active = job_scheduler.kill_switch.is_active
    original_sleep = job_scheduler.time.sleep
    original_prace_w_toku = job_scheduler.prace_w_toku

    kolejnosc = []

    job_scheduler.scheduler_lock.acquire = lambda: {"ok": True, "detail": "test"}
    job_scheduler.scheduler_lock.release = lambda: None
    job_scheduler.kill_switch.is_active = lambda: False
    # "Coś jest w toku" -> wstrzymany bot NIE zamyka jeszcze procesu, pętla tyka dalej.
    job_scheduler.prace_w_toku = lambda *args, **kwargs: ["runner_loop"]

    def _fake_sync(role=None, **kwargs):
        kolejnosc.append("sync")
        return "todo"

    def _fake_is_paused():
        kolejnosc.append("is_paused")
        return True  # bot "wstrzymany" -> pętla robi `continue` zaraz po sprawdzeniu, bez dispatchu jobów

    licznik_snu = {"n": 0}

    def _fake_sleep(seconds):
        licznik_snu["n"] += 1
        if licznik_snu["n"] >= 3:
            raise _StopPetli()

    remote_control.sync = _fake_sync
    job_scheduler.control.is_paused = _fake_is_paused
    job_scheduler.time.sleep = _fake_sleep

    try:
        try:
            job_scheduler.run_scheduler(tick_seconds=0)
        except _StopPetli:
            pass

        checks.append(("remote_control.sync() wywołane na KAŻDYM ticku (3 razy)",
                       kolejnosc.count("sync") == 3))
        checks.append(("sync() wołane PRZED control.is_paused() w KAŻDYM ticku (priorytet)",
                       all(kolejnosc[i] == "sync" and kolejnosc[i + 1] == "is_paused"
                           for i in range(0, len(kolejnosc), 2))))
    finally:
        job_scheduler.scheduler_lock.acquire = original_acquire
        job_scheduler.scheduler_lock.release = original_release
        remote_control.sync = original_sync
        job_scheduler.control.is_paused = original_is_paused
        job_scheduler.kill_switch.is_active = original_kill_active
        job_scheduler.time.sleep = original_sleep
        job_scheduler.prace_w_toku = original_prace_w_toku

    print("\n--- Wynik testu dymnego: priorytet remote_control.sync() w job_scheduler ---")
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
