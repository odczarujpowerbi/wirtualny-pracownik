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

# "assignee" == "asia"/"kacper" (zamiast konta AI) - te dwa zadania testowe
# reprezentują WŁASNE zadania bota w testach 1/1b/2/3 (assignee dowolny,
# own_account=None w tych wywołaniach = filtr wyłączony). Izolacja po koncie
# AI (żywy bug 29.08.2026) ma OSOBNY fixture niżej (TASKS_IZOLACJA).
TASKS = [
    {"task_id": "T-1", "title": "Zadanie 1", "status": "done", "assignee": "asia"},
    {"task_id": "T-2", "title": "Zadanie 2", "status": "done", "assignee": "kacper"},
    {"task_id": "T-3", "title": "Zadanie 3", "status": "todo", "assignee": "asia"},
]

# Fixture dedykowany testowi izolacji: dwa zadania WŁASNEGO konta bota +
# jedno człowieka + jedno innego bota, wszystkie "done" - bez filtru po
# assignee wszystkie cztery kwalifikowałyby się do feedbacku (żywy bug).
OWN_ACCOUNT = "AI - Test"
TASKS_IZOLACJA = [
    {"task_id": "T-WLASNE-1", "title": "Własne zadanie 1", "status": "done", "assignee": OWN_ACCOUNT},
    {"task_id": "T-WLASNE-2", "title": "Własne zadanie 2", "status": "done", "assignee": OWN_ACCOUNT},
    {"task_id": "T-CZLOWIEK", "title": "Zadanie człowieka", "status": "done", "assignee": "Kasia"},
    {"task_id": "T-INNY-BOT", "title": "Zadanie innego bota", "status": "done", "assignee": "AI - Marketing"},
]


class _FakeClient:
    def __init__(self, pada_na_task_id=None, tasks=None):
        self.komentarze = []
        self.utworzone = []
        self.pada_na_task_id = pada_na_task_id
        self.tasks = tasks if tasks is not None else TASKS

    def list_tasks(self):
        return self.tasks

    def post_comment(self, task_id, text):
        if task_id == self.pada_na_task_id:
            raise RuntimeError("Symulowany błąd sieci/Projectly w środku listy.")
        self.komentarze.append((task_id, text))
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None,
                    project_id=None, relation_type="kontynuacja", priority=None):
        self.utworzone.append({"title": title, "parent_task_id": parent_task_id, "priority": priority})
        return f"FB-{len(self.utworzone)}"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_asked_path = tfr.ASKED_PATH
    original_generate_draft = tfr.generate_draft
    original_own_account_name = tfr.own_account_name

    wolania_maila = []
    tfr.generate_draft = lambda *a, **k: wolania_maila.append((a, k)) or {"ok": True}
    # Testy 1-5 używają zadań "asia"/"kacper" jako WŁASNYCH (own_account=None
    # w wywołaniach bezpośrednich, filtr wyłączony) - dla run_feedback_requests(),
    # które woła own_account_name() naprawdę, podkładamy atrapę zwracającą None
    # (żeby nie zależeć od realnego config/projectly.yaml + BOT_ROLE maszyny
    # testowej). Izolacja po realnym koncie ma OSOBNY blok niżej z inną atrapą.
    tfr.own_account_name = lambda: None

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
        checks.append(("request_feedback_for_task: zadanie feedbackowe ma priorytet BACKLOG (3)",
                       client.utworzone[0]["priority"] == tfr.PRIORITY_BACKLOG))

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

        # --- 6. Izolacja: bot dotyka WYŁĄCZNIE zadań własnego konta AI (żywy
        # bug 29.08.2026, żądanie właściciela: "żadnych innych"). Bez filtru
        # T-CZLOWIEK i T-INNY-BOT też dostałyby komentarz/zadanie feedbackowe. ---
        checks.append(("find_tasks_needing_feedback: BEZ own_account -> widzi też cudze zadania",
                       {t["task_id"] for t in tfr.find_tasks_needing_feedback(TASKS_IZOLACJA, set())}
                       == {"T-WLASNE-1", "T-WLASNE-2", "T-CZLOWIEK", "T-INNY-BOT"}))
        checks.append(("find_tasks_needing_feedback: Z own_account -> WYŁĄCZNIE własne konto",
                       {t["task_id"] for t in tfr.find_tasks_needing_feedback(TASKS_IZOLACJA, set(), own_account=OWN_ACCOUNT)}
                       == {"T-WLASNE-1", "T-WLASNE-2"}))

        tfr.own_account_name = lambda: OWN_ACCOUNT
        tfr.ASKED_PATH = tmp / "feedback_requested_izolacja.json"
        client_izolacja = _FakeClient(tasks=TASKS_IZOLACJA)
        tfr.run_feedback_requests(client=client_izolacja)
        checks.append(("run_feedback_requests: komentarz/zadanie feedbackowe TYLKO na własnych zadaniach",
                       {tid for tid, _ in client_izolacja.komentarze} == {"T-WLASNE-1", "T-WLASNE-2"}))
        checks.append(("run_feedback_requests: cudze zadania (człowiek/inny bot) NIGDY nie dostają komentarza",
                       all(tid not in {"T-CZLOWIEK", "T-INNY-BOT"} for tid, _ in client_izolacja.komentarze)))
    finally:
        tfr.ASKED_PATH = original_asked_path
        tfr.generate_draft = original_generate_draft
        tfr.own_account_name = original_own_account_name

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
