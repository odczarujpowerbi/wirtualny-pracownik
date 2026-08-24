"""
Test dymny runner_loop._save_result_to_onedrive — sprawdza, że dla każdego
przetworzonego zadania powstaje DOKŁADNIE JEDEN plik wynik_<task_id>.<format>
w per-zadaniowym folderze (gdzie format wybiera output_decider.decide(),
Agent sterujący), oraz że podzadanie (parent_task_id ustawione, patrz
task_decomposer.py) pisze do folderu RODZICA, nie tworzy własnego. Zero
sieci — task_thinker.ask_model jest podmieniany atrapą, żeby test nie
zależał od prawdziwego wywołania modelu.

Użycie:
    python runner_loop_onedrive_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import runner_loop
import task_thinker

TASK = {"task_id": "T-XLSX", "title": "Zestawienie kampanii MailerLite"}
TABLE_ROWS = [
    {"id": "111", "nazwa": "Newsletter 33", "odbiorcy": 2400, "otwarcia": 840},
    {"id": "222", "nazwa": "Webinar", "odbiorcy": 2380, "otwarcia": 1020},
]


def _atrapa(text, available=True, source="claude_code"):
    return lambda prompt, caller=None: {"available": available, "text": text,
                                        "source": source, "detail": "OK"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    original_ask_model = task_thinker.ask_model

    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)

            # 1. Happy path: model wybiera xlsx, execution_result ma table_rows ->
            #    dokładnie jeden plik, wynik_<task_id>.xlsx.
            os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")
            task_thinker.ask_model = _atrapa('{"format": "xlsx", "reasoning": "Dane liczbowe."}')
            execution_result = {"acceptance_notes": "Zestawienie kampanii.", "table_rows": TABLE_ROWS}
            folder = runner_loop._save_result_to_onedrive(TASK, "done", "Zrobione.", execution_result)
            checks.append(("Zwrócono ścieżkę folderu", folder is not None))
            folder_path = Path(folder) if folder else None
            checks.append(("wynik_T-XLSX.xlsx istnieje",
                           folder_path is not None and (folder_path / "wynik_T-XLSX.xlsx").exists()))
            checks.append(("Dokładnie JEDEN plik wynik_*.* w folderze",
                           folder_path is not None and len(list(folder_path.glob("wynik_*.*"))) == 1))

            # 2. Model niedostępny -> fail-closed na PDF, wciąż dokładnie jeden plik.
            task_thinker.ask_model = _atrapa(None, available=False)
            folder2 = runner_loop._save_result_to_onedrive(
                {"task_id": "T-BEZ-MODELU", "title": "Zadanie bez modelu"}, "done", "Zrobione.",
                {"acceptance_notes": "Wynik bez table_rows."})
            folder2_path = Path(folder2) if folder2 else None
            checks.append(("Brak modelu: wynik_T-BEZ-MODELU.pdf istnieje (fail-closed default)",
                           folder2_path is not None and (folder2_path / "wynik_T-BEZ-MODELU.pdf").exists()))
            checks.append(("Brak modelu: dokładnie JEDEN plik wynik_*.*",
                           folder2_path is not None and len(list(folder2_path.glob("wynik_*.*"))) == 1))

            # 3. Bez execution_result (np. wczesna eskalacja prompt injection) -> wciąż
            #    powstaje plik, treść budowana z samego comment.
            task_thinker.ask_model = _atrapa('{"format": "md", "reasoning": "Notatka techniczna."}')
            folder3 = runner_loop._save_result_to_onedrive(
                {"task_id": "T-BEZ-EXEC", "title": "Eskalacja bez execution_result"}, "needs_approval",
                "Wykryto podejrzaną treść.")
            folder3_path = Path(folder3) if folder3 else None
            checks.append(("Bez execution_result: plik i tak powstaje",
                           folder3_path is not None and (folder3_path / "wynik_T-BEZ-EXEC.md").exists()))

            # 3b. Podzadanie (parent_task_id ustawione) pisze do folderu RODZICA
            #     (glob po prefiksie task_id), nie tworzy własnego folderu — bez
            #     lokalnego mapowania, źródłem prawdy jest samo Projectly.
            task_thinker.ask_model = _atrapa('{"format": "pdf", "reasoning": "Do wysłania."}')
            folder_child = runner_loop._save_result_to_onedrive(
                {"task_id": "T-DZIECKO-1", "title": "Podzadanie 1", "parent_task_id": "T-XLSX"},
                "done", "Podzadanie zrobione.", {"acceptance_notes": "Wynik podzadania."})
            checks.append(("Podzadanie: folder taki sam jak rodzica (T-XLSX_*)",
                           folder_child == folder))
            checks.append(("Podzadanie: własny plik wynik_T-DZIECKO-1.* w folderze rodzica",
                           folder_path is not None and (folder_path / "wynik_T-DZIECKO-1.pdf").exists()))
            checks.append(("Współdzielony folder: pliki rodzica i dziecka NIE nadpisują się",
                           folder_path is not None and len(list(folder_path.glob("wynik_*.*"))) == 2))

            # 4. Error case: katalog nadrzędny ONEDRIVE_TASKS_ROOT nie istnieje ->
            #    fail-soft, zwraca None, nie rzuca (model nie jest nawet wołany).
            os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "brak_takiego_katalogu" / "Zadania-Agenta")
            folder_missing = runner_loop._save_result_to_onedrive(TASK, "done", "Zrobione.", execution_result)
            checks.append(("Brak zsynchronizowanego OneDrive -> None, bez wyjątku", folder_missing is None))

            # 5. Error case: brak ONEDRIVE_TASKS_ROOT w env -> None.
            del os.environ["ONEDRIVE_TASKS_ROOT"]
            folder_no_env = runner_loop._save_result_to_onedrive(TASK, "done", "Zrobione.", execution_result)
            checks.append(("Brak ONEDRIVE_TASKS_ROOT -> None, bez wyjątku", folder_no_env is None))
    finally:
        task_thinker.ask_model = original_ask_model
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
