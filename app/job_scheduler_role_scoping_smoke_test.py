"""
Test dymny scope'owania job_scheduler.py per ROLA (dodane 29.08.2026, żeby
kilka procesów job_scheduler.py na tej samej maszynie/repo — dev/checker/
marketing, patrz BOT_ROLE w env_bootstrap._current_role — mogło działać
niezależnie): osobne pliki stanu/historii i filtr, który job odpala która rola.

Zero realnej pętli run_scheduler() (wymagałaby wątków/blokady plikowej) —
testowane są wyodrębnione, czyste funkcje (_status_path_for_role,
_history_path_for_role, _job_runs_under_role).

Użycie:
    python job_scheduler_role_scoping_smoke_test.py
"""

import sys

import job_scheduler


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- ścieżki stanu/historii: "dev" bez sufiksu (wsteczna zgodność) ---
    checks.append(("_status_path_for_role('dev') -> nazwa BEZ sufiksu",
                   job_scheduler._status_path_for_role("dev").name == "scheduler_status.json"))
    checks.append(("_history_path_for_role('dev') -> nazwa BEZ sufiksu",
                   job_scheduler._history_path_for_role("dev").name == "run_history.jsonl"))

    checks.append(("_status_path_for_role('checker') -> osobny plik",
                   job_scheduler._status_path_for_role("checker").name == "scheduler_status_checker.json"))
    checks.append(("_history_path_for_role('marketing') -> osobny plik",
                   job_scheduler._history_path_for_role("marketing").name == "run_history_marketing.jsonl"))
    checks.append(("dev i checker mają RÓŻNE pliki stanu (nie nadpisują się nawzajem)",
                   job_scheduler._status_path_for_role("dev") != job_scheduler._status_path_for_role("checker")))

    # --- filtr: który job odpala która rola ---
    job_bez_pola = {"name": "system_health_monitor"}
    job_dev_jawnie = {"name": "runner_loop", "role": "dev"}
    job_checker = {"name": "repo_auto_improver", "role": "checker"}

    checks.append(("Job BEZ pola 'role' -> domyślnie 'dev' (wsteczna zgodność)",
                   job_scheduler._job_runs_under_role(job_bez_pola, "dev") is True
                   and job_scheduler._job_runs_under_role(job_bez_pola, "checker") is False))
    checks.append(("Job z role='dev' jawnie -> tylko proces dev",
                   job_scheduler._job_runs_under_role(job_dev_jawnie, "dev") is True
                   and job_scheduler._job_runs_under_role(job_dev_jawnie, "checker") is False))
    checks.append(("Job z role='checker' -> WYŁĄCZNIE proces checker, nie dev",
                   job_scheduler._job_runs_under_role(job_checker, "checker") is True
                   and job_scheduler._job_runs_under_role(job_checker, "dev") is False))

    print("\n--- Wynik testu dymnego job_scheduler (role scoping) ---")
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
