"""
Test dymny runner_loop._save_result_to_onedrive — konkretnie eksportu
analiza.xlsx obok wynik.md, gdy execution_result niesie table_rows (decyzja
właściciela 24.08.2026, patrz docstring funkcji). Zero sieci, zero prawdziwego
OneDrive — ONEDRIVE_TASKS_ROOT wskazuje na katalog tymczasowy.

Użycie:
    python runner_loop_onedrive_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import runner_loop

TASK = {"task_id": "T-XLSX", "title": "Zestawienie kampanii MailerLite"}
TABLE_ROWS = [
    {"id": "111", "nazwa": "Newsletter 33", "odbiorcy": 2400, "otwarcia": 840},
    {"id": "222", "nazwa": "Webinar", "odbiorcy": 2380, "otwarcia": 1020},
]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            # 1. Happy path: execution_result z table_rows -> wynik.md I analiza.xlsx.
            os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")
            execution_result = {"table_title": "Kampanie MailerLite", "table_rows": TABLE_ROWS}
            folder = runner_loop._save_result_to_onedrive(TASK, "done", "Zrobione.", execution_result)
            checks.append(("Zwrócono ścieżkę folderu", folder is not None))
            folder_path = Path(folder) if folder else None
            checks.append(("wynik.md istnieje", folder_path is not None and (folder_path / "wynik.md").exists()))
            xlsx_path = folder_path / "analiza.xlsx" if folder_path else None
            checks.append(("analiza.xlsx istnieje", xlsx_path is not None and xlsx_path.exists()))
            checks.append(("analiza.xlsx nie jest pusty",
                           xlsx_path is not None and xlsx_path.exists() and xlsx_path.stat().st_size > 0))

            # 2. Regresja: bez table_rows (albo bez execution_result) -> tylko wynik.md,
            #    zachowanie sprzed zmiany.
            folder2 = runner_loop._save_result_to_onedrive(
                {"task_id": "T-BEZ-XLSX", "title": "Zadanie bez danych tabelarycznych"}, "done", "Zrobione.")
            folder2_path = Path(folder2) if folder2 else None
            checks.append(("Bez execution_result: wynik.md istnieje",
                           folder2_path is not None and (folder2_path / "wynik.md").exists()))
            checks.append(("Bez execution_result: brak analiza.xlsx",
                           folder2_path is not None and not (folder2_path / "analiza.xlsx").exists()))

            folder3 = runner_loop._save_result_to_onedrive(
                {"task_id": "T-PUSTE-ROWS", "title": "Zadanie z puste table_rows"}, "done", "Zrobione.",
                {"table_rows": []})
            folder3_path = Path(folder3) if folder3 else None
            checks.append(("table_rows=[] (puste) -> brak analiza.xlsx",
                           folder3_path is not None and not (folder3_path / "analiza.xlsx").exists()))

            # 3. Error case: katalog nadrzędny ONEDRIVE_TASKS_ROOT nie istnieje ->
            #    fail-soft, zwraca None, nie rzuca.
            os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "brak_takiego_katalogu" / "Zadania-Agenta")
            folder_missing = runner_loop._save_result_to_onedrive(TASK, "done", "Zrobione.", execution_result)
            checks.append(("Brak zsynchronizowanego OneDrive -> None, bez wyjątku", folder_missing is None))

            # 4. Error case: brak ONEDRIVE_TASKS_ROOT w env -> None.
            del os.environ["ONEDRIVE_TASKS_ROOT"]
            folder_no_env = runner_loop._save_result_to_onedrive(TASK, "done", "Zrobione.", execution_result)
            checks.append(("Brak ONEDRIVE_TASKS_ROOT -> None, bez wyjątku", folder_no_env is None))
    finally:
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu dymnego runner_loop (_save_result_to_onedrive) ---")
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
