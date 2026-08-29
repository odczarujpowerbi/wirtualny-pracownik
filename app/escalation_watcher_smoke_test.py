"""
Test dymny escalation_watcher.py. Zero sieci — klient Projectly to atrapa
zbierająca wywołania. state_store.DB_PATH izolowany (event log), stan
kursora (runs/escalation_watcher_state*.json) w tymczasowym pliku.

Użycie:
    python escalation_watcher_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import escalation_watcher as ew
import state_store
from projectly_client import PRIORITY_BIEZACE

OWN_ACCOUNT = "AI - Test"


class _FakeClient:
    def __init__(self, tasks, comments=None):
        self.tasks = tasks
        self.comments = comments or {}
        self.posted_comments = []
        self.utworzone = []

    def list_tasks(self):
        return self.tasks

    def get_comments(self, task_id):
        return self.comments.get(task_id, [])

    def post_comment(self, task_id, text):
        self.posted_comments.append((task_id, text))
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None,
                    project_id=None, relation_type="kontynuacja", priority=None, due_date=None):
        new_id = f"KONT-{len(self.utworzone) + 1}"
        self.utworzone.append({"task_id": new_id, "title": title, "description": description,
                              "parent_task_id": parent_task_id, "priority": priority})
        return new_id


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_own_account_name = ew.own_account_name

    try:
        state_store.DB_PATH = tmp / "state.db"
        ew.own_account_name = lambda role=None: OWN_ACCOUNT

        # --- 1. Eskalacja "done" + wystarczający komentarz -> kontynuacja
        # utworzona, wisi pod zadaniem GŁÓWNYM eskalacji (nie pod eskalacją). ---
        tasks_1 = [
            {"task_id": "ESK-1", "title": "Wymaga decyzji: Zadanie A", "status": "done",
             "assignee": OWN_ACCOUNT, "parent_task_id": "GLOWNE-A", "priority": PRIORITY_BIEZACE},
        ]
        client_1 = _FakeClient(tasks_1, comments={"ESK-1": ["Zatwierdzam, kontynuuj."]})
        wynik_1 = ew.run_once(client=client_1, state_path=tmp / "state1.json")
        checks.append(("run_once: wystarczający komentarz -> kontynuacja utworzona",
                       len(client_1.utworzone) == 1))
        checks.append(("run_once: kontynuacja wisi pod zadaniem GŁÓWNYM eskalacji",
                       client_1.utworzone[0]["parent_task_id"] == "GLOWNE-A"))
        checks.append(("run_once: BRAK komentarza z prośbą o doprecyzowanie (odpowiedź była wystarczająca)",
                       client_1.posted_comments == []))
        checks.append(("run_once: zdarzenie 'continuation' w wyniku", wynik_1["events"][0]["kind"] == "continuation"))

        # Drugi przebieg na tym samym stanie -> BEZ drugiej kontynuacji (już obsłużone).
        ew.run_once(client=client_1, state_path=tmp / "state1.json")
        checks.append(("run_once: drugi przebieg NIE dubluje kontynuacji (już obsłużone)",
                       len(client_1.utworzone) == 1))

        # --- 2. Eskalacja "done" + NIEwystarczający komentarz -> tylko prośba
        # o doprecyzowanie, BRAK kontynuacji. ---
        tasks_2 = [
            {"task_id": "ESK-2", "title": "Wymaga decyzji: Zadanie B", "status": "done", "assignee": OWN_ACCOUNT},
        ]
        client_2 = _FakeClient(tasks_2, comments={"ESK-2": ["A o co dokładnie chodzi?"]})
        ew.run_once(client=client_2, state_path=tmp / "state2.json")
        checks.append(("run_once: niewystarczający komentarz -> BRAK kontynuacji", client_2.utworzone == []))
        checks.append(("run_once: niewystarczający komentarz -> komentarz z prośbą o doprecyzowanie",
                       len(client_2.posted_comments) == 1 and client_2.posted_comments[0][0] == "ESK-2"))

        # Drugi przebieg tego samego dnia -> BRAK drugiego identycznego dopytania (dedup).
        ew.run_once(client=client_2, state_path=tmp / "state2.json")
        checks.append(("run_once: dedup dopytania per dzień — brak drugiego komentarza",
                       len(client_2.posted_comments) == 1))

        # --- 3. Cudza eskalacja (inny assignee) -> pominięta całkowicie (WS1). ---
        tasks_3 = [
            {"task_id": "ESK-CUDZE", "title": "Wymaga decyzji: Zadanie cudze", "status": "done",
             "assignee": "AI - Marketing"},
        ]
        client_3 = _FakeClient(tasks_3, comments={"ESK-CUDZE": ["Zatwierdzam."]})
        wynik_3 = ew.run_once(client=client_3, state_path=tmp / "state3.json")
        checks.append(("run_once: cudza eskalacja (inny assignee) pominięta — 0 zeskanowanych", wynik_3["scanned"] == 0))
        checks.append(("run_once: cudza eskalacja — BRAK kontynuacji/komentarza", client_3.utworzone == []
                       and client_3.posted_comments == []))

        # --- 4. Eskalacja otwarta (status != done), termin minął ->
        # przypomnienie (dedup per dzień, dwa warianty pola: due_date/dueDate). ---
        tasks_4 = [
            {"task_id": "ESK-OVERDUE", "title": "Wymaga decyzji: Zadanie C", "status": "todo",
             "assignee": OWN_ACCOUNT, "due_date": "2020-01-01"},
        ]
        client_4 = _FakeClient(tasks_4)
        ew.run_once(client=client_4, state_path=tmp / "state4.json")
        checks.append(("run_once: przeterminowana, wciąż otwarta eskalacja -> przypomnienie",
                       len(client_4.posted_comments) == 1))
        ew.run_once(client=client_4, state_path=tmp / "state4.json")
        checks.append(("run_once: dedup przypomnienia per dzień — brak drugiego",
                       len(client_4.posted_comments) == 1))

        # --- 5. Otwarta, termin JESZCZE nie minął -> BRAK przypomnienia. ---
        tasks_5 = [
            {"task_id": "ESK-OK", "title": "Wymaga decyzji: Zadanie D", "status": "todo",
             "assignee": OWN_ACCOUNT, "due_date": "2099-01-01"},
        ]
        client_5 = _FakeClient(tasks_5)
        ew.run_once(client=client_5, state_path=tmp / "state5.json")
        checks.append(("run_once: termin jeszcze nie minął -> brak przypomnienia", client_5.posted_comments == []))

        # --- 6. Zadania BEZ prefiksu eskalacji -> całkowicie ignorowane. ---
        tasks_6 = [{"task_id": "ZWYKLE", "title": "Zwykłe zadanie", "status": "done", "assignee": OWN_ACCOUNT}]
        client_6 = _FakeClient(tasks_6, comments={"ZWYKLE": ["Zatwierdzam."]})
        wynik_6 = ew.run_once(client=client_6, state_path=tmp / "state6.json")
        checks.append(("run_once: zadanie bez prefiksu eskalacji ignorowane", wynik_6["scanned"] == 0))
    finally:
        state_store.DB_PATH = original_db_path
        ew.own_account_name = original_own_account_name

    print("\n--- Wynik testu dymnego escalation_watcher ---")
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
