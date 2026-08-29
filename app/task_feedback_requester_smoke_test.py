"""
Test dymny task_feedback_requester. Pilnuje dwóch rzeczy, których brak wywołał
żywą eskalację ("Feedback: Feedback: Analiza rozmów 1:1 czerwiec ..."):

1. Zadanie feedbackowe NIE dostaje własnego zadania feedbackowego (brak pętli).
2. Opis nowego zadania niesie fakty z zadania źródłowego (estymacja, czas realny,
   termin, komentarze) albo nazywa ich brak wprost, a zadanie ma cel i kryteria
   akceptacji — bez tego wykonawca musiałby zmyślać, a bramka jakości odrzuca.

Klient jest podstawiony (fake), więc test nie dotyka sieci ani plików mocka.

Użycie:
    python task_feedback_requester_smoke_test.py
"""

import sys

import task_feedback_requester


class FakeClient:
    """Podstawiony Projectly (zewnętrzny serwis) — zapamiętuje wywołania."""

    def __init__(self, comments=None):
        self._comments = comments or {}
        self.created = []
        self.posted = []

    def get_comments(self, task_id):
        return self._comments.get(task_id, [])

    def post_comment(self, task_id, text):
        self.posted.append((task_id, text))
        self._comments.setdefault(task_id, []).append(text)
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None,
                    relation_type="eskalacja", expected_result=None, acceptance_criteria=None):
        self.created.append({
            "title": title, "description": description, "assigned_to": assigned_to,
            "parent_task_id": parent_task_id, "project_id": project_id,
            "relation_type": relation_type, "expected_result": expected_result,
            "acceptance_criteria": acceptance_criteria,
        })
        return f"PRJ-FB-{len(self.created):04d}"


def _checks_filtrowania():
    tasks = [
        {"task_id": "PRJ-1", "title": "Analiza rozmów 1:1 czerwiec", "status": "done"},
        {"task_id": "PRJ-2", "title": "Feedback: Analiza rozmów 1:1 czerwiec", "status": "done"},
        {"task_id": "PRJ-3", "title": "Raport tygodniowy", "status": "in_progress"},
        {"task_id": "PRJ-4", "title": "Zamknięte wcześniej", "status": "done"},
    ]
    wybrane = task_feedback_requester.find_tasks_needing_feedback(tasks, already_asked={"PRJ-4"})
    ids = [t["task_id"] for t in wybrane]
    return [
        ("zamknięte zadanie merytoryczne kwalifikuje się", ids == ["PRJ-1"]),
        ("zadanie feedbackowe NIE dostaje własnego feedbacku", "PRJ-2" not in ids),
        ("niezamknięte pomijane", "PRJ-3" not in ids),
        ("już zapytane pomijane", "PRJ-4" not in ids),
        ("rozpoznanie zadania feedbackowego po tytule", task_feedback_requester.is_feedback_task(tasks[1])),
    ]


def _checks_opisu_z_danymi():
    task = {
        "task_id": "PRJ-1", "project_id": "organizacyjne", "status": "done",
        "title": "Analiza rozmów 1:1 czerwiec", "assignee": "asia",
        "estimatedHours": 4, "actualHours": 6.5, "dueDate": "2026-06-30",
        "completedAt": "2026-07-02",
    }
    client = FakeClient(comments={"PRJ-1": ["Utknęłam na eksporcie notatek z OneNote."]})

    wynik = task_feedback_requester.request_feedback_for_task(task, client=client, send_email=False)
    utworzone = client.created[0]
    opis = utworzone["description"]

    return [
        ("zwrócono id nowego zadania", wynik["feedback_task_id"] == "PRJ-FB-0001"),
        ("pytanie poszło komentarzem na zadanie źródłowe", client.posted[0][0] == "PRJ-1"),
        ("opis niesie id zadania źródłowego", "PRJ-1" in opis),
        ("opis niesie estymację", "4 h" in opis),
        ("opis niesie czas realny", "6.5 h" in opis),
        ("opis niesie termin", "2026-06-30" in opis),
        ("opis niesie komentarz z wątku", "OneNote" in opis),
        ("opis NIE cytuje własnego pytania bota", "👋" not in opis),
        ("zadanie ma cel (goal)", bool(utworzone["expected_result"])),
        ("zadanie ma kryteria akceptacji (effect)", bool(utworzone["acceptance_criteria"])),
        ("powiązanie z rodzicem typu kontynuacja",
         utworzone["parent_task_id"] == "PRJ-1" and utworzone["relation_type"] == "kontynuacja"),
    ]


def _checks_brakow():
    task = {"task_id": "PRJ-9", "title": "Zadanie bez danych", "status": "done", "assignee": None}
    client = FakeClient()
    task_feedback_requester.request_feedback_for_task(task, client=client, send_email=False)
    utworzone = client.created[0]
    opis = utworzone["description"]

    return [
        ("brak estymacji nazwany wprost", task_feedback_requester.BRAK in opis),
        ("opis nie zawiera 'None' jako wartości", ": None" not in opis),
        ("brak assignee -> pula", utworzone["assigned_to"] == "unassigned_pool"),
        ("kryteria dopuszczają uczciwe 'brak danych'",
         task_feedback_requester.BRAK in utworzone["acceptance_criteria"]),
    ]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = _checks_filtrowania() + _checks_opisu_z_danymi() + _checks_brakow()

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
