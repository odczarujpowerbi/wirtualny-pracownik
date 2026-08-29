"""
Test dymny task_feedback_requester.py. Zero sieci — klient Projectly to atrapa
zbierająca wywołania, `email_draft_generator.generate_draft` podmieniony
atrapą (test nie ma sprawdzać maila, tylko czy w ogóle jest wołany).
`ASKED_PATH` izolowany (tymczasowy plik) — zero wpływu na realny
runs/feedback_requested.json.

Użycie:
    python task_feedback_requester_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import task_feedback_requester as tfr

TASKS = [
    {"task_id": "T-1", "title": "Zadanie 1", "status": "done", "assignee": "asia"},
    {"task_id": "T-2", "title": "Zadanie 2", "status": "done", "assignee": "kacper"},
    {"task_id": "T-3", "title": "Zadanie 3", "status": "todo", "assignee": "asia"},
]


class _FakeClient:
    def __init__(self, pada_na_task_id=None):
        self.komentarze = []
        self.utworzone = []
        self.pada_na_task_id = pada_na_task_id

    def list_tasks(self):
        return TASKS

    def post_comment(self, task_id, text):
        if task_id == self.pada_na_task_id:
            raise RuntimeError("Symulowany błąd sieci/Projectly w środku listy.")
        self.komentarze.append((task_id, text))
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None,
                    project_id=None, relation_type="kontynuacja"):
        self.utworzone.append({"title": title, "parent_task_id": parent_task_id})
        return f"FB-{len(self.utworzone)}"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_asked_path = tfr.ASKED_PATH
    original_generate_draft = tfr.generate_draft

    wolania_maila = []
    tfr.generate_draft = lambda *a, **k: wolania_maila.append((a, k)) or {"ok": True}

    try:
        tfr.ASKED_PATH = tmp / "feedback_requested.json"

        # --- 1. find_tasks_needing_feedback: tylko 'done' i jeszcze nie zapytane ---
        do_zapytania = tfr.find_tasks_needing_feedback(TASKS, already_asked=set())
        checks.append(("find_tasks_needing_feedback: tylko status='done'",
                       {t["task_id"] for t in do_zapytania} == {"T-1", "T-2"}))
        checks.append(("find_tasks_needing_feedback: pomija już zapytane",
                       {t["task_id"] for t in tfr.find_tasks_needing_feedback(TASKS, {"T-1"})} == {"T-2"}))

        # --- 1b. Żywy bug 29.08.2026 (ten sam wzorzec co escalation.py
        # ESCALATION_TITLE_PREFIX): zadanie FEEDBACKOWE, utworzone przez ten
        # skrypt, samo dostaje status "done" (zamknięte przez człowieka) —
        # NIE może być traktowane jak zwykłe "done" zadanie, inaczej dokleja
        # się kolejny prefiks w kółko ("Feedback: Feedback: ...").
        zadania_z_meta = TASKS + [
            {"task_id": "T-FB-META", "title": "Feedback: Zadanie 1", "status": "done", "assignee": "asia"},
        ]
        do_zapytania_z_meta = tfr.find_tasks_needing_feedback(zadania_z_meta, already_asked=set())
        checks.append(("find_tasks_needing_feedback: pomija WŁASNE zadania feedbackowe (tytuł 'Feedback: ...')",
                       "T-FB-META" not in {t["task_id"] for t in do_zapytania_z_meta}
                       and {t["task_id"] for t in do_zapytania_z_meta} == {"T-1", "T-2"}))

        # Defense-in-depth: nawet wywołane wprost, request_feedback_for_task
        # NIE dokleja drugiego prefiksu do już-prefiksowanego tytułu.
        client_meta = _FakeClient()
        tfr.request_feedback_for_task(
            {"task_id": "T-FB-META", "title": "Feedback: Zadanie 1", "assignee": "asia"}, client=client_meta)
        checks.append(("request_feedback_for_task: BRAK podwójnego prefiksu 'Feedback: Feedback: ...'",
                       client_meta.utworzone[0]["title"] == "Feedback: Zadanie 1"))

        # --- 2. domyślnie send_email=False — mail NIE jest wołany ---
        client = _FakeClient()
        wynik = tfr.request_feedback_for_task(TASKS[0], client=client)
        checks.append(("request_feedback_for_task: domyślnie send_email=False -> brak wołania maila",
                       len(wolania_maila) == 0 and wynik["email"] is None))
        checks.append(("request_feedback_for_task: komentarz i zadanie feedbackowe i tak powstają",
                       len(client.komentarze) == 1 and len(client.utworzone) == 1))

        # --- 3. send_email=True jawnie -> mail wołany ---
        wolania_maila.clear()
        tfr.request_feedback_for_task(TASKS[1], client=client, send_email=True)
        checks.append(("request_feedback_for_task: send_email=True jawnie -> mail wołany",
                       len(wolania_maila) == 1))

        # --- 4. run_feedback_requests: domyślnie send_email=False dla całej partii ---
        wolania_maila.clear()
        client2 = _FakeClient()
        tfr.run_feedback_requests(client=client2)
        checks.append(("run_feedback_requests: domyślnie send_email=False dla całej partii",
                       len(wolania_maila) == 0))
        checks.append(("run_feedback_requests: przetworzono dokładnie zadania 'done'", len(client2.komentarze) == 2))

        # --- 5. odporność na błąd w środku listy: co już zrobione NIE powtarza się ---
        # Świeży ASKED_PATH — inaczej T-1/T-2 byłyby już "zapytane" z kroku 4
        # i to_ask wyszłoby puste, nie testując wcale odporności na przerwanie.
        tfr.ASKED_PATH = tmp / "feedback_requested_crash.json"
        client3 = _FakeClient(pada_na_task_id="T-2")
        try:
            tfr.run_feedback_requests(client=client3)
        except RuntimeError:
            pass
        checks.append(("Po błędzie w środku: T-1 zostało naprawdę zapisane jako zapytane",
                       "T-1" in tfr._load_asked()))
        checks.append(("Po błędzie w środku: T-2 (to, co padło) NIE jest zapisane jako zapytane",
                       "T-2" not in tfr._load_asked()))

        client4 = _FakeClient()  # drugi przebieg, bez błędu — T-2 powinno dojść, T-1 nie powtórzyć się
        tfr.run_feedback_requests(client=client4)
        checks.append(("Kolejny przebieg: T-1 NIE przetworzone drugi raz (brak duplikatu komentarza)",
                       all(tid != "T-1" for tid, _ in client4.komentarze)))
        checks.append(("Kolejny przebieg: T-2 (przerwane wcześniej) dochodzi do końca",
                       any(tid == "T-2" for tid, _ in client4.komentarze) and "T-2" in tfr._load_asked()))
    finally:
        tfr.ASKED_PATH = original_asked_path
        tfr.generate_draft = original_generate_draft

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
