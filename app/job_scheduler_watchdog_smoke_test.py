"""
Test dymny job_scheduler._watchdog_timeout_exceeded — druga linia obrony na
zawieszony wątek joba (żywy incydent 25.08.2026: runner_loop/notebook_intake/
kacper_monitor/system_health_monitor zamarły na 2+ godziny; naprawa sieciowa
w mcp_client.py to pierwsza linia, ta funkcja to backstop na wypadek
JAKIEJKOLWIEK innej przyszłej przyczyny zawieszenia).

Zero realnej pętli run_scheduler()/blokady plikowej — ten test sprawdza tylko
wyodrębnioną decyzję ("czy ten wątek żyje już za długo"), bez ryzyka
interferencji z żywym procesem job_scheduler.py na maszynie.

Użycie:
    python job_scheduler_watchdog_smoke_test.py
"""

import sys
from datetime import datetime, timedelta, timezone

import job_scheduler


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    now = datetime(2026, 8, 25, 18, 0, 0, tzinfo=timezone.utc)

    checks.append(("started_at=None -> nigdy nie 'zawieszony' (jeszcze nie odpalony)",
                   job_scheduler._watchdog_timeout_exceeded(None, now, 1800) is False))

    started_niedawno = now - timedelta(seconds=60)
    checks.append(("wątek żyje 60s, limit 1800s -> NIE zawieszony",
                   job_scheduler._watchdog_timeout_exceeded(started_niedawno, now, 1800) is False))

    started_dawno = now - timedelta(seconds=1801)
    checks.append(("wątek żyje 1801s, limit 1800s -> ZAWIESZONY",
                   job_scheduler._watchdog_timeout_exceeded(started_dawno, now, 1800) is True))

    started_dokladnie = now - timedelta(seconds=1800)
    checks.append(("wątek żyje RÓWNO limit -> jeszcze NIE zawieszony (ostra nierówność)",
                   job_scheduler._watchdog_timeout_exceeded(started_dokladnie, now, 1800) is False))

    # Żywy incydent 25.08.2026: 2 godziny (7200s) to dokładnie ten scenariusz,
    # który miał zostać złapany.
    started_2h = now - timedelta(hours=2)
    checks.append(("wątek żyje 2h, domyślny limit (1800s) -> ZAWIESZONY",
                   job_scheduler._watchdog_timeout_exceeded(
                       started_2h, now, job_scheduler.DEFAULT_MAX_DURATION_SECONDS) is True))

    # runner_loop dostał podwyższony limit w schedule.default.yaml (może legalnie
    # przetwarzać zadania agentic_worker do 600s każde, do 5 na przebieg) —
    # 2h i tak przekracza NAWET podwyższony limit 3600s, więc watchdog wciąż łapie.
    checks.append(("wątek żyje 2h, podwyższony limit runner_loop (3600s) -> WCIĄŻ zawieszony",
                   job_scheduler._watchdog_timeout_exceeded(started_2h, now, 3600) is True))

    schedule = job_scheduler.load_schedule(job_scheduler.DEFAULT_SCHEDULE_PATH)
    runner_loop_job = next(j for j in schedule if j["name"] == "runner_loop")
    checks.append(("schedule.default.yaml: runner_loop ma podwyższony max_duration_seconds",
                   runner_loop_job.get("max_duration_seconds", 0) > job_scheduler.DEFAULT_MAX_DURATION_SECONDS))

    print("\n--- Wynik testu dymnego job_scheduler (watchdog) ---")
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
