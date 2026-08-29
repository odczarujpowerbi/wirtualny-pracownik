"""
Test dymny dashboardu i rozszerzeń job_scheduler.py (historia przebiegów,
uruchamianie na żądanie, edycja harmonogramu). Uruchamialny lokalnie, bez
kluczy API — używa tymczasowego harmonogramu i tymczasowych plików stanu,
NIE dotyka prawdziwego config/schedule.yaml ani runs/.

Użycie:
    python dashboard_smoke_test.py
"""

import sys
import tempfile
import types
from pathlib import Path

import dashboard
import job_scheduler


def _install_fake_jobs_module():
    """Moduł z bezargumentowymi funkcjami do odpalenia przez scheduler:
    jedna wypisuje coś i zwraca wartość, druga celowo rzuca błąd."""
    mod = types.ModuleType("dash_test_job")
    mod.calls = []

    def _ok():
        mod.calls.append("ok")
        print("zrobione: przetworzono 3 rekordy")
        return {"processed": 3}
    mod.run_ok = _ok

    def _boom():
        raise RuntimeError("celowy błąd zadania")
    mod.run_boom = _boom

    sys.modules["dash_test_job"] = mod
    return mod


def _write_schedule(path):
    jobs = [
        {"name": "ok_job", "description": "opis", "module": "dash_test_job",
         "function": "run_ok", "interval_seconds": 30, "enabled": True},
        {"name": "boom_job", "description": "opis", "module": "dash_test_job",
         "function": "run_boom", "interval_seconds": 60, "enabled": True},
    ]
    job_scheduler.save_schedule(jobs, path)


def run():
    # Konsola Windows bywa w cp1250 i wywala się na ✅/❌ — wymuszamy UTF-8.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    fake = _install_fake_jobs_module()

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        schedule_path = tmp / "schedule.yaml"
        # Przekieruj pliki stanu na tymczasowe, żeby nie ruszać prawdziwego runs/.
        job_scheduler.STATUS_PATH = tmp / "status.json"
        job_scheduler.HISTORY_PATH = tmp / "history.jsonl"
        _write_schedule(schedule_path)

        # 1. Edycja harmonogramu (interwał + wyłączenie + opis naraz).
        job_scheduler.update_job("ok_job",
                                 {"interval_seconds": 120, "enabled": False, "description": "nowy opis"},
                                 path=schedule_path)
        jobs = {j["name"]: j for j in job_scheduler.load_schedule(schedule_path)}
        checks.append(("update_job zmienia interwał/enabled/opis",
                       jobs["ok_job"]["interval_seconds"] == 120
                       and jobs["ok_job"]["enabled"] is False
                       and jobs["ok_job"]["description"] == "nowy opis"))

        # 2. update_job na nieistniejącym zadaniu -> błąd (error case).
        try:
            job_scheduler.update_job("nie_ma", {"enabled": True}, path=schedule_path)
            raised = False
        except ValueError:
            raised = True
        checks.append(("update_job na nieznanym zadaniu rzuca ValueError", raised))

        # 3. Uruchomienie na żądanie zadania OK -> status ok, id przebiegu, wpis w historii.
        result = job_scheduler.run_job_by_name("ok_job", path=schedule_path)
        checks.append(("run_job_by_name odpala funkcję, raportuje ok i zwraca last_run_id",
                       "ok" in fake.calls and result["last_status"] == "ok" and result["last_run_id"]))

        # 4. Zadanie, które rzuca -> status error, scheduler nie wywala się (error case).
        result_boom = job_scheduler.run_job_by_name("boom_job", path=schedule_path)
        checks.append(("run_job_by_name łapie błąd zadania jako error",
                       result_boom["last_status"] == "error" and result_boom["last_error"]))

        # 5. run_job_by_name na nieistniejącym zadaniu -> ValueError (error case).
        try:
            job_scheduler.run_job_by_name("nie_ma", path=schedule_path)
            raised_run = False
        except ValueError:
            raised_run = True
        checks.append(("run_job_by_name na nieznanym zadaniu rzuca ValueError", raised_run))

        # 6. Historia: najnowszy pierwszy, oba przebiegi, źródło 'manual', BEZ output.
        history = job_scheduler.load_history(limit=10)
        checks.append(("load_history zwraca przebiegi, najnowszy pierwszy, źródło manual, bez output",
                       len(history) == 2 and history[0]["name"] == "boom_job"
                       and history[0]["trigger"] == "manual" and "output" not in history[0]))

        # 7. Szczegół przebiegu OK: przechwycone wyjście (stdout) i zwrócona wartość.
        ok_log = job_scheduler.get_run_log(result["last_run_id"])
        checks.append(("get_run_log zwraca przechwycone stdout i zwróconą wartość",
                       ok_log is not None and "przetworzono 3 rekordy" in ok_log["output"]
                       and "processed" in (ok_log.get("result") or "")))

        # 8. Szczegół przebiegu z błędem: traceback trafia do output.
        boom_log = job_scheduler.get_run_log(result_boom["last_run_id"])
        checks.append(("get_run_log dla błędu ma traceback w output",
                       boom_log is not None and "RuntimeError" in boom_log["output"]))

        # 9. get_run_log dla nieznanego id -> None (error case).
        checks.append(("get_run_log dla nieznanego id zwraca None",
                       job_scheduler.get_run_log("nie-ma-takiego") is None))

    # 10. Walidacja pól z UI: poprawny zestaw przechodzi.
    updates = dashboard._validate_updates({"interval_seconds": 45, "enabled": True, "description": " x "})
    checks.append(("_validate_updates przepuszcza poprawne pola i trimuje opis",
                   updates == {"interval_seconds": 45, "enabled": True, "description": "x"}))

    # 11. Walidacja: nie-dodatni interwał odrzucony (error case).
    try:
        dashboard._validate_updates({"interval_seconds": 0})
        rejected = False
    except ValueError:
        rejected = True
    checks.append(("_validate_updates odrzuca interwał <= 0", rejected))

    # 12. build_state: zagregowany widok WSZYSTKICH ról naraz (dev/checker),
    # dodane 29.08.2026 razem z podziałem stanu/historii per rola. Izolacja
    # PEŁNA (w tym discover_roles i CURRENT_ROLE) — zero dotknięcia prawdziwego
    # runs/ tej maszyny.
    original_status_path = job_scheduler.STATUS_PATH
    original_history_path = job_scheduler.HISTORY_PATH
    original_current_role = job_scheduler.CURRENT_ROLE
    original_discover_roles = job_scheduler.discover_roles
    original_status_path_for_role = job_scheduler._status_path_for_role
    original_history_path_for_role = job_scheduler._history_path_for_role
    try:
        with tempfile.TemporaryDirectory() as tmp3:
            tmp3 = Path(tmp3)
            job_scheduler.STATUS_PATH = tmp3 / "status_dev.json"
            job_scheduler.HISTORY_PATH = tmp3 / "history_dev.jsonl"
            job_scheduler.CURRENT_ROLE = "dev"
            job_scheduler.discover_roles = lambda *a, **k: ["dev", "checker"]

            job_scheduler.STATUS_PATH.write_text('{"runner_loop": {"last_status": "ok"}}', encoding="utf-8")
            job_scheduler.HISTORY_PATH.write_text(
                '{"id": "d1", "name": "runner_loop", "run_at": "2026-08-29T10:00:00+00:00", "status": "ok"}\n',
                encoding="utf-8")
            (tmp3 / "scheduler_status_checker.json").write_text(
                '{"repo_auto_improver": {"last_status": "ok"}}', encoding="utf-8")
            (tmp3 / "run_history_checker.jsonl").write_text(
                '{"id": "c1", "name": "repo_auto_improver", "run_at": "2026-08-29T11:00:00+00:00", "status": "ok"}\n',
                encoding="utf-8")
            job_scheduler._status_path_for_role = lambda rola: tmp3 / f"scheduler_status_{rola}.json"
            job_scheduler._history_path_for_role = lambda rola: tmp3 / f"run_history_{rola}.jsonl"

            state = dashboard.build_state()
        checks.append(("build_state zwraca jobs/status/history",
                       set(state) == {"jobs", "status", "history"} and isinstance(state["jobs"], list)))
        checks.append(("build_state: status zawiera joby OBU ról, każdy oznaczony swoją rolą",
                       state["status"].get("runner_loop", {}).get("role") == "dev"
                       and state["status"].get("repo_auto_improver", {}).get("role") == "checker"))
        checks.append(("build_state: historia zawiera przebiegi OBU ról, najnowszy pierwszy",
                       len(state["history"]) == 2 and state["history"][0]["name"] == "repo_auto_improver"
                       and state["history"][0]["role"] == "checker"
                       and state["history"][1]["role"] == "dev"))
    finally:
        job_scheduler.STATUS_PATH = original_status_path
        job_scheduler.HISTORY_PATH = original_history_path
        job_scheduler.CURRENT_ROLE = original_current_role
        job_scheduler.discover_roles = original_discover_roles
        job_scheduler._status_path_for_role = original_status_path_for_role
        job_scheduler._history_path_for_role = original_history_path_for_role

    # 13. build_tasks zwraca strukturę zadań (grupowanie po zadaniu, read-only).
    tasks = dashboard.build_tasks()
    checks.append(("build_tasks zwraca listę zadań", isinstance(tasks.get("tasks"), list)))

    # 14. append_task (formularz "Dodaj zadanie") buduje linię w formacie parsera.
    import notebook_intake
    with tempfile.TemporaryDirectory() as tmp2:
        inbox = Path(tmp2) / "zadania.txt"
        line = notebook_intake.append_task("Test zadania", risk="red",
                                           project_path="mock_data/sample_pbip", inbox_path=inbox)
        checks.append(("append_task buduje linię z @ ścieżką i !red",
                       line == "Test zadania @ mock_data/sample_pbip !red"
                       and inbox.read_text(encoding="utf-8").strip() == line))

        # 15. Round-trip: dopisana linia parsuje się z powrotem na poprawne zadanie.
        parsed = notebook_intake.parse_notebook(line)[0]
        checks.append(("append_task -> parse_notebook round-trip (red + validate_pbip)",
                       parsed["risk_level_hint"] == "red" and parsed["action"] == "validate_pbip"
                       and parsed["project_path"] == "mock_data/sample_pbip"))

        # 16. Pusta treść zadania odrzucona (error case).
        try:
            notebook_intake.append_task("   ", inbox_path=inbox)
            empty_rejected = False
        except ValueError:
            empty_rejected = True
        checks.append(("append_task odrzuca pustą treść", empty_rejected))

    # 17. build_health zwraca stan sterowania + metryki kondycji (read-only).
    health = dashboard.build_health()
    checks.append(("build_health zwraca stan sterowania i metryki",
                   health.get("control") in ("running", "paused", "stopped")
                   and "queue_depth" in health and "cost_today_usd" in health))

    # 18-22. Przyciski "uruchom agenta X" (dodane 29.08.2026, do testowania) —
    # zero realnego spawnowania procesów: scheduler_lock.is_running i
    # dashboard._launch_process podmienione atrapami.
    import scheduler_lock
    original_agent_bat_files = dashboard.AGENT_BAT_FILES
    original_is_running = scheduler_lock.is_running
    original_launch_process = dashboard._launch_process
    uruchomienia = []
    dashboard._launch_process = lambda cmd, cwd: uruchomienia.append((cmd, cwd))

    with tempfile.TemporaryDirectory() as tmp4:
        tmp4 = Path(tmp4)
        bat_dev = tmp4 / "dev.bat"
        bat_dev.write_text("@echo off\n", encoding="utf-8")
        bat_checker = tmp4 / "checker.bat"
        bat_checker.write_text("@echo off\n", encoding="utf-8")
        dashboard.AGENT_BAT_FILES = {
            "dev": bat_dev, "checker": bat_checker, "marketing": tmp4 / "brak-tego-pliku.bat",
        }
        try:
            # 18. build_agents: status każdej roli wg scheduler_lock.is_running.
            scheduler_lock.is_running = lambda role: role == "dev"
            agenci = dashboard.build_agents()
            stany = {a["role"]: a["running"] for a in agenci["agents"]}
            checks.append(("build_agents: zwraca status KAŻDEJ znanej roli, zgodny z is_running",
                           stany == {"dev": True, "checker": False, "marketing": False}))

            # 19. start_agent: rola już działająca -> NIE odpala nowego procesu.
            wynik_juz_dziala = dashboard.start_agent("dev")
            checks.append(("start_agent: agent już działający -> started=False, BRAK nowego procesu",
                           wynik_juz_dziala["started"] is False and len(uruchomienia) == 0))

            # 20. start_agent: rola nieznana -> błąd czytelny, bez wyjątku.
            wynik_nieznana = dashboard.start_agent("nieistniejąca-rola")
            checks.append(("start_agent: nieznana rola -> started=False, komunikat, bez wyjątku",
                           wynik_nieznana["started"] is False and "Nieznana rola" in wynik_nieznana["message"]))

            # 21. start_agent: brak pliku .bat -> błąd czytelny (error case).
            wynik_brak_pliku = dashboard.start_agent("marketing")
            checks.append(("start_agent: brak pliku .bat -> started=False, BRAK nowego procesu",
                           wynik_brak_pliku["started"] is False and len(uruchomienia) == 0))

            # 22. start_agent: rola NIE działająca, plik istnieje -> odpala proces.
            wynik_start = dashboard.start_agent("checker")
            checks.append(("start_agent: agent nieaktywny + plik istnieje -> started=True, proces odpalony",
                           wynik_start["started"] is True and len(uruchomienia) == 1
                           and str(bat_checker) in uruchomienia[0][0]))

            # 23. start_all_agents: agreguje wynik dla WSZYSTKICH ról naraz.
            uruchomienia.clear()
            wynik_wszystkie = dashboard.start_all_agents()
            checks.append(("start_all_agents: zwraca wynik dla każdej znanej roli",
                           set(wynik_wszystkie["results"]) == {"dev", "checker", "marketing"}))
            checks.append(("start_all_agents: 'dev' już działał (started=False), 'marketing' bez pliku (started=False)",
                           wynik_wszystkie["results"]["dev"]["started"] is False
                           and wynik_wszystkie["results"]["marketing"]["started"] is False))
        finally:
            scheduler_lock.is_running = original_is_running
            dashboard.AGENT_BAT_FILES = original_agent_bat_files
            dashboard._launch_process = original_launch_process

    print("\n--- Wynik testu dymnego dashboardu ---")
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
