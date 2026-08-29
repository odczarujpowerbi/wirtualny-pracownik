"""
Test dymny prośby o feedback. Bez sieci i bez plików — klient Projectly jest
atrapą, mail wyłączony (send_email=False).

Powód istnienia: zadanie "Feedback: Feedback: Dodanie godzin do aplikacji"
poszło na eskalację do człowieka. Dwie przyczyny po stronie tego modułu:
prośba o feedback rodziła się z zadania feedbackowego (stąd podwojony prefiks),
a jej opis nie niósł ŻADNYCH danych ani kryteriów odbioru, więc nie dało się jej
wykonać ani ocenić.

Użycie:
    python task_feedback_requester_smoke_test.py
"""

import sys

import task_feedback_requester as tfr


class _FakeClient:
    """Atrapa Projectly — zapamiętuje, z czym ją wywołano."""

    def __init__(self):
        self.comments = []
        self.created = []

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None,
                    relation_type="eskalacja", expected_result=None, acceptance_criteria=None):
        self.created.append({
            "title": title, "description": description, "assigned_to": assigned_to,
            "parent_task_id": parent_task_id, "project_id": project_id,
            "relation_type": relation_type, "expected_result": expected_result,
            "acceptance_criteria": acceptance_criteria,
        })
        return f"FB-{len(self.created):04d}"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- odsiewanie zadań: co w ogóle kwalifikuje się do prośby o feedback ---
    tasks = [
        {"task_id": "T-1", "title": "Dodanie godzin do aplikacji", "status": "done"},
        {"task_id": "T-2", "title": "Feedback: Dodanie godzin do aplikacji", "status": "done"},
        {"task_id": "T-3", "title": "Jeszcze w robocie", "status": "in_progress"},
        {"task_id": "T-4", "title": "Zamknięte dawno", "status": "done"},
    ]
    wybrane = [t["task_id"] for t in tfr.find_tasks_needing_feedback(tasks, {"T-4"})]
    checks.append(("Zamknięte zadanie trafia pod prośbę o feedback", wybrane == ["T-1"]))
    checks.append(("Zadanie feedbackowe NIE rodzi kolejnego feedbacku (bez 'Feedback: Feedback:')",
                   "T-2" not in wybrane))
    checks.append(("Niezamknięte zadanie pomijane", "T-3" not in wybrane))
    checks.append(("Już zapytane zadanie pomijane", "T-4" not in wybrane))

    # --- odchylenie czasu: liczba dla wykonawcy, nie zadanie do policzenia ---
    checks.append(("Odchylenie liczone z estymacji i czasu realnego",
                   tfr.format_deviation(4, 6).startswith("+2 h (+50%)")))
    checks.append(("Godziny jako tekst też się liczą", tfr.format_deviation("4", "3").startswith("-1 h")))
    checks.append(("Brak jednej z liczb -> jawnie nazwany brak, bez zmyślania",
                   tfr.BRAK_DANYCH in tfr.format_deviation(4, None)))

    # --- brief: dane z Projectly zamiast samego pytania ---
    zadanie = {"task_id": "T-1", "title": "Dodanie godzin do aplikacji", "status": "done",
               "assignee": "Aldona", "estimated_hours": 4, "actual_hours": 6,
               "due_date": "2026-08-20", "completed_at": "2026-08-22", "project_id": "P-9"}
    brief = tfr.build_feedback_brief(zadanie)
    checks.append(("Brief wskazuje zadanie źródłowe po id", "T-1" in brief))
    checks.append(("Brief niesie estymację", "4 h" in brief))
    checks.append(("Brief niesie czas realny", "6 h" in brief))
    checks.append(("Brief niesie wyliczone odchylenie", "+2 h (+50%)" in brief))
    checks.append(("Brief niesie wykonawcę", "Aldona" in brief))
    checks.append(("Brief nadal zawiera same pytania", tfr.FEEDBACK_COMMENT in brief))

    puste = tfr.build_feedback_brief({"task_id": "T-5", "title": "Bez danych"})
    checks.append(("Brak danych nazwany wprost, brief się nie wywala", tfr.BRAK_DANYCH in puste))

    # --- utworzone zadanie: tytuł, cel i kryteria odbioru ---
    client = _FakeClient()
    wynik = tfr.request_feedback_for_task(zadanie, client=client, send_email=False)
    utworzone = client.created[0]
    checks.append(("Prośba trafia komentarzem do zadania źródłowego",
                   client.comments == [("T-1", tfr.FEEDBACK_COMMENT)]))
    checks.append(("Tytuł ma dokładnie jeden prefiks 'Feedback: '",
                   utworzone["title"] == "Feedback: Dodanie godzin do aplikacji"))
    checks.append(("Zadanie feedbackowe ma CEL (bramka ma co oceniać)",
                   bool(utworzone["expected_result"])))
    checks.append(("Zadanie feedbackowe ma KRYTERIA ODBIORU",
                   bool(utworzone["acceptance_criteria"])))
    checks.append(("Kryteria dopuszczają odpowiedź 'brakuje danych' jako wykonanie",
                   "nie jego brak" in utworzone["acceptance_criteria"]))
    checks.append(("Opis to brief z danymi, nie samo pytanie",
                   "+2 h (+50%)" in utworzone["description"]))
    checks.append(("Zadanie powiązane z oryginałem jako kontynuacja",
                   utworzone["parent_task_id"] == "T-1" and utworzone["relation_type"] == "kontynuacja"))
    checks.append(("Zwrócone id nowego zadania", wynik["feedback_task_id"] == "FB-0001"))

    # assignee=None (klucz ISTNIEJE z wartością None — .get(k, domyślne) by tego nie złapał)
    client_bez = _FakeClient()
    tfr.request_feedback_for_task(
        {"task_id": "T-6", "title": "Bez przypisania", "assignee": None, "project_id": "P-9"},
        client=client_bez, send_email=False)
    checks.append(("Brak przypisania -> unassigned_pool, nie None",
                   client_bez.created[0]["assigned_to"] == "unassigned_pool"))

    print("\n--- Wynik testu dymnego prośby o feedback ---")
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
