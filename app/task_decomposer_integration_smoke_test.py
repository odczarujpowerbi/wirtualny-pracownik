"""
Test dymny integracyjny: pełny przebieg runner_loop.process_task() na zadaniu
BEZ rozpoznanego workera, gdzie model (atrapa) każe rozbić na podzadania.
Sprawdza całą ścieżkę na raz: task_decomposer -> projectly_client (Mock) ->
status "przeniesione" -> _save_result_to_onedrive. Używa TYMCZASOWEJ bazy
(state_store.DB_PATH) i tymczasowych plików MockProjectlyClient — nie dotyka
żywych runs/*.json. Wpina się automatycznie w self_check.py.

Użycie:
    python task_decomposer_integration_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import risk_classifier
import runner_loop
import state_store
import task_router
import task_thinker
from projectly_client import MockProjectlyClient

TASK = {"task_id": "T-INTEGR", "title": "Przygotuj pełny audyt konkurencji i raport",
        "expected_result": "Raport z analizą konkurencji", "acceptance_criteria": "",
        "description": "", "risk_level_hint": "yellow", "project_id": "PROJ-1"}

DECYZJA_JSON = (
    '{"split": true, "reasoning": "Za duże na jeden krok.", "subtasks": ['
    '{"title": "Zbierz dane o konkurentach", "description": "Lista 5 konkurentów"}, '
    '{"title": "Porównaj ceny", "description": "Tabela porównawcza"}, '
    '{"title": "Napisz podsumowanie", "description": "Krótki raport"}]}'
)


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    original_ask_model = task_thinker.ask_model

    try:
        state_store.DB_PATH = tmp / "state.db"
        os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")
        task_thinker.ask_model = lambda prompt, caller=None: {
            "available": True, "text": DECYZJA_JSON, "source": "claude_code", "detail": "OK",
        }

        client = MockProjectlyClient()
        client._created_tasks_path = tmp / "created.json"
        client._comments_path = tmp / "comments.json"
        client._feedback_path = tmp / "feedback.json"
        client._agent_status_path = tmp / "agent_status.json"

        policy = risk_classifier.load_policy()
        routing = task_router.load_routing()
        result = runner_loop.process_task(TASK, policy, routing, client)

        checks.append(("Status zadania głównego = przeniesione", result.get("status") == "przeniesione"))

        created = client._load(client._created_tasks_path, default=[])
        checks.append(("3 podzadania utworzone w Projectly (mock)", len(created) == 3))
        checks.append(("Każde podzadanie ma subtask_of = T-INTEGR",
                       all(c.get("subtask_of") == "T-INTEGR" for c in created)))
        checks.append(("Każde podzadanie w tym samym projekcie co rodzic",
                       all(c.get("project_id") == "PROJ-1" for c in created)))

        comments = client._load(client._comments_path, default={})
        checks.append(("Komentarz z listą podzadań na zadaniu głównym",
                       "T-INTEGR" in comments and len(comments["T-INTEGR"]) == 1))

        onedrive_root = Path(os.environ["ONEDRIVE_TASKS_ROOT"])
        folders = list(onedrive_root.glob("T-INTEGR_*"))
        checks.append(("Dokładnie jeden folder wyniku dla zadania głównego", len(folders) == 1))
        if folders:
            wynik_files = list(folders[0].glob("wynik_*.*"))
            checks.append(("Dokładnie jeden plik wyniku w folderze", len(wynik_files) == 1))
    finally:
        task_thinker.ask_model = original_ask_model
        state_store.DB_PATH = original_db_path
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu integracyjnego dekompozycji zadania ---")
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
