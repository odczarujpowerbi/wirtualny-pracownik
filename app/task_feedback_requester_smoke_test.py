"""
Test dymny task_feedback_requester. Pilnuje dwóch rzeczy:

1. Mechanizm NIE pyta o feedback do zadań, które sam założył (feedback,
   eskalacja, kontynuacja) — inaczej napędza sam siebie: "Feedback: X" ->
   "Feedback: Feedback: X" -> ... (żywy przebieg opisany w task_titles.py).
2. Zwykłe zamknięte zadanie nadal dostaje pytanie, dokładnie raz.

Użycie:
    python task_feedback_requester_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import task_feedback_requester
import task_titles


class StubClient:
    """Podstawka za Projectly (usługa zewnętrzna) — zapamiętuje, co powstało."""

    def __init__(self, tasks):
        self.tasks = tasks
        self.created = []
        self.comments = []

    def list_tasks(self, project_id=None, status=None):
        return self.tasks

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None,
                    relation_type="eskalacja", expected_result=None, acceptance_criteria=None):
        new_id = f"STUB-{len(self.created) + 1:04d}"
        self.created.append({"task_id": new_id, "title": title, "assigned_to": assigned_to,
                             "parent_task_id": parent_task_id})
        return new_id


def _task(task_id, title, status="done", assignee="pawel"):
    return {"task_id": task_id, "title": title, "status": status,
            "assignee": assignee, "project_id": "PRJ-1"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    zadania = [
        _task("T-1", "Ustalenie źródła danych i zakresu inwentaryzacji SharePoint"),
        _task("T-2", "Feedback: Ustalenie źródła danych i zakresu inwentaryzacji SharePoint"),
        _task("T-3", "Wymaga decyzji: Ustalenie źródła danych i zakresu inwentaryzacji SharePoint"),
        _task("T-4", "Kontynuacja: Ustalenie źródła danych i zakresu inwentaryzacji SharePoint"),
        _task("T-5", "Przepięcie źródła w raporcie Magnapharm", status="in_progress"),
    ]
    wybrane = [t["task_id"] for t in task_feedback_requester.find_tasks_needing_feedback(zadania, set())]

    checks = [
        ("zwykłe zamknięte zadanie trafia do pytania o feedback", wybrane == ["T-1"]),
        ("zadanie feedbackowe NIE rodzi kolejnego feedbacku", "T-2" not in wybrane),
        ("zadanie eskalacyjne NIE dostaje pytania o feedback", "T-3" not in wybrane),
        ("zadanie kontynuacyjne NIE dostaje pytania o feedback", "T-4" not in wybrane),
        ("niezamknięte zadanie nie dostaje pytania", "T-5" not in wybrane),
        ("już zapytane zadanie nie wraca",
         task_feedback_requester.find_tasks_needing_feedback(zadania, {"T-1"}) == []),
        ("prefiks nie nakłada się drugi raz",
         task_titles.derived_title(task_titles.PREFIX_FEEDBACK, "Feedback: X") == "Feedback: X"),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        asked_path = Path(tmp) / "feedback_requested.json"

        client = StubClient(zadania)
        pierwszy = task_feedback_requester.run_feedback_requests(
            client=client, send_email=False, asked_path=asked_path)
        drugi = task_feedback_requester.run_feedback_requests(
            client=client, send_email=False, asked_path=asked_path)

        checks.append(("przebieg zakłada dokładnie jedno zadanie feedbackowe", len(pierwszy) == 1))
        checks.append(("tytuł nowego zadania to 'Feedback: <oryginał>'",
                       client.created[0]["title"] == "Feedback: " + zadania[0]["title"]))
        checks.append(("nowe zadanie wisi przy oryginale",
                       client.created[0]["parent_task_id"] == "T-1"))
        checks.append(("drugi przebieg nie pyta ponownie", drugi == [] and len(client.created) == 1))

        # Zadanie bez przypisania: 'assignee' jest w kontrakcie, ale None.
        bez_osoby = StubClient([_task("T-9", "Zebranie danych do raportu", assignee=None)])
        task_feedback_requester.run_feedback_requests(
            client=bez_osoby, send_email=False, asked_path=Path(tmp) / "inne.json")
        checks.append(("zadanie bez assignee idzie do unassigned_pool, nie do None",
                       bez_osoby.created[0]["assigned_to"] == "unassigned_pool"))

    print("\n--- Wynik testu dymnego task_feedback_requester ---")
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
