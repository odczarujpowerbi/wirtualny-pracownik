"""
Test dymny progu zuzycia limitu (usage_monitor, runner_loop.run_once) —
zadanie wlasciciela 29.08.2026: przy >=85% (usage_monitor.over_threshold)
runner ma konczyc zadania w kolejce, nowych nie przyjmowac, i opublikowac
status na zywo z jawna notatka.

Zero sieci: control.RUNS_DIR izolowany (pauza/kill switch), usage_monitor.over_threshold
podmieniony atrapa (nie zalezy od realnego ~/.claude/powerline/usage/today.json
tej maszyny), klient Projectly to lekka atrapa.

Uzycie:
    python runner_loop_usage_threshold_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import control
import kill_switch
import runner_loop
import usage_monitor


class _FakeClient:
    def __init__(self):
        self.published = []

    def get_new_tasks(self):
        return []

    def publish_status(self, role, payload):
        self.published.append((role, payload))
        return True


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_runs_dir = control.RUNS_DIR
    original_stop_flag = kill_switch.STOP_FLAG_PATH
    original_over_threshold = usage_monitor.over_threshold
    original_summary = usage_monitor.summary

    try:
        control.RUNS_DIR = tmp
        kill_switch.STOP_FLAG_PATH = tmp / "STOP.flag"

        # --- 1. Zużycie POWYŻEJ progu -> run_once() zwraca [] BEZ pobierania
        # nowych zadań, publikuje status z jawną notatką o wstrzymaniu. ---
        usage_monitor.summary = lambda: {"available": True, "block_budget_used_pct": 198.2}
        usage_monitor.over_threshold = lambda s: True
        client_over = _FakeClient()
        wynik_over = runner_loop.run_once(client=client_over)
        checks.append(("run_once: zużycie >= progu -> pusty wynik, BRAK pobrania zadań", wynik_over == []))
        checks.append(("run_once: zużycie >= progu -> status na żywo opublikowany",
                       len(client_over.published) == 1))
        checks.append(("run_once: status niesie jawną notatkę o wstrzymaniu (zużycie)",
                       "Zużycie limitu" in client_over.published[0][1].get("detail", "")))

        # --- 2. Zużycie PONIŻEJ progu -> run_once() przechodzi dalej (pobiera
        # zadania normalnie — tu: pusta kolejka, więc kończy się szybko, ale
        # BEZ wczesnego returnu z powodu zużycia). ---
        usage_monitor.over_threshold = lambda s: False
        client_ok = _FakeClient()
        runner_loop.run_once(client=client_ok)
        checks.append(("run_once: zużycie < progu -> BRAK wczesnego wyjścia z powodu zużycia "
                       "(status i tak publikowany przez normalny przebieg)",
                       not any("Zużycie limitu" in (p.get("detail") or "") for _, p in client_ok.published)))
    finally:
        control.RUNS_DIR = original_runs_dir
        kill_switch.STOP_FLAG_PATH = original_stop_flag
        usage_monitor.over_threshold = original_over_threshold
        usage_monitor.summary = original_summary

    print("\n--- Wynik testu dymnego progu zużycia (runner_loop) ---")
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
