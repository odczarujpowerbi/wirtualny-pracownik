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

    # 12. build_state ma komplet kluczy i czyta zadeklarowane zadania (read-only).
    state = dashboard.build_state()
    checks.append(("build_state zwraca jobs/status/history",
                   set(state) == {"jobs", "status", "history"} and isinstance(state["jobs"], list)))

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
