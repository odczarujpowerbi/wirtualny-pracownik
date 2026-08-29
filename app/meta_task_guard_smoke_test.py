"""
Test dymny progu meta-zadań: agent nie wykonuje ani nie eskaluje zadań, które
sam założył dla człowieka, a tytuły eskalacji/kontynuacji/feedbacku nie
narastają przedrostkami.

Powód istnienia (żywy przebieg 29.08.2026): eskalacja wracała w get_new_tasks,
runner brał ją jak zwykłe zadanie i eskalował ponownie. W Projectly rosło
"Wymaga decyzji: Feedback: Wymaga decyzji: Wymaga decyzji: Zbierz dane o Looker
Studio, Metabase i Superset (fetch_url)", a człowiek dostawał kolejne kopie tego
samego pytania.

Baza podmieniona na tymczasową — test nie dotyka żywego runs/state.db.

Użycie:
    python meta_task_guard_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import meta_task_guard
import state_store

ZAGNIEZDZONY_TYTUL = ("Wymaga decyzji: Feedback: Wymaga decyzji: Wymaga decyzji: "
                      "Zbierz dane o Looker Studio, Metabase i Superset (fetch_url)")
CZYSTY_TYTUL = "Zbierz dane o Looker Studio, Metabase i Superset (fetch_url)"


class FakeClient:
    """Liczy, co runner zrobiłby w Projectly. Zadanie dla człowieka nie może
    wywołać ŻADNEJ z tych metod."""

    def __init__(self):
        self.created = []
        self.comments = []
        self.statuses = []

    def create_task(self, title, description, assigned_to, parent_task_id=None,
                    project_id=None, relation_type="eskalacja", **kwargs):
        self.created.append({"title": title, "assigned_to": assigned_to,
                             "relation_type": relation_type})
        return f"PRJ-ESC-{len(self.created):04d}"

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True

    def update_status(self, task_id, status):
        self.statuses.append((task_id, status))
        return True


def _use_temp_db():
    state_store.DB_PATH = Path(tempfile.mkdtemp()) / "test_state.db"


def _testy_tytulow():
    checks = []

    checks.append(("Zagnieżdżone przedrostki zdjęte do czystego tytułu",
                   meta_task_guard.strip_meta_prefixes(ZAGNIEZDZONY_TYTUL) == CZYSTY_TYTUL))
    checks.append(("Tytuł bez przedrostka zostaje bez zmian",
                   meta_task_guard.strip_meta_prefixes(CZYSTY_TYTUL) == CZYSTY_TYTUL))
    checks.append(("Tytuł złożony z samych przedrostków nie znika",
                   meta_task_guard.strip_meta_prefixes("Wymaga decyzji:") == "Wymaga decyzji:"))

    raz = meta_task_guard.escalation_title(CZYSTY_TYTUL)
    checks.append(("Eskalacja dokłada jeden przedrostek", raz == f"Wymaga decyzji: {CZYSTY_TYTUL}"))
    checks.append(("Eskalacja eskalacji nie dokłada drugiego",
                   meta_task_guard.escalation_title(raz) == raz))
    checks.append(("Eskalacja zagnieżdżonego tytułu wraca do jednego przedrostka",
                   meta_task_guard.escalation_title(ZAGNIEZDZONY_TYTUL) == raz))
    checks.append(("Kontynuacja jest idempotentna",
                   meta_task_guard.continuation_title(meta_task_guard.continuation_title(CZYSTY_TYTUL))
                   == f"Kontynuacja: {CZYSTY_TYTUL}"))
    checks.append(("Feedback jest idempotentny",
                   meta_task_guard.feedback_title(meta_task_guard.feedback_title(CZYSTY_TYTUL))
                   == f"Feedback: {CZYSTY_TYTUL}"))

    checks.append(("Eskalacja to zadanie dla człowieka",
                   meta_task_guard.is_for_human({"title": raz}) is True))
    checks.append(("Prośba o feedback to zadanie dla człowieka",
                   meta_task_guard.is_for_human({"title": f"Feedback: {CZYSTY_TYTUL}"}) is True))
    checks.append(("Kontynuacja to zadanie DLA AGENTA, nie dla człowieka",
                   meta_task_guard.is_for_human({"title": f"Kontynuacja: {CZYSTY_TYTUL}"}) is False))
    checks.append(("Zwykłe zadanie nie jest meta-zadaniem",
                   meta_task_guard.is_meta_task({"title": CZYSTY_TYTUL}) is False))
    checks.append(("Kontynuacja JEST meta-zadaniem (nie pytamy o feedback do niej)",
                   meta_task_guard.is_meta_task({"title": f"Kontynuacja: {CZYSTY_TYTUL}"}) is True))
    checks.append(("Zadanie bez tytułu nie wywraca sprawdzenia",
                   meta_task_guard.is_for_human({}) is False))
    return checks


def _testy_runnera():
    import runner_loop

    _use_temp_db()
    checks = []
    client = FakeClient()
    zadanie = {"task_id": "PRJ-ESC-0001", "title": f"Wymaga decyzji: {CZYSTY_TYTUL}",
               "project_id": "PRJ-1"}

    wynik = runner_loop.process_task(zadanie, policy={}, routing={}, client=client)
    checks.append(("Zadanie dla człowieka odłożone, nie przetworzone",
                   wynik["status"] == runner_loop.WAITING_HUMAN))
    checks.append(("Odłożone zadanie NIE tworzy kolejnej eskalacji", client.created == []))
    checks.append(("Odłożone zadanie NIE komentuje w kółko", client.comments == []))
    checks.append(("Odłożone zadanie NIE zmienia statusu w Projectly", client.statuses == []))

    zdarzenia = state_store.get_events("PRJ-ESC-0001")
    checks.append(("Pominięcie zapisane w dzienniku",
                   [e for e in zdarzenia if e["event_type"] == "escalation_task_skipped"] != []))
    checks.append(("Pominięcie NIE domyka bloku (block_closed)",
                   [e for e in zdarzenia if e["event_type"] == "block_closed"] == []))

    runner_loop.process_task(zadanie, policy={}, routing={}, client=client)
    ponowne = [e for e in state_store.get_events("PRJ-ESC-0001")
               if e["event_type"] == "escalation_task_skipped"]
    checks.append(("Kolejny cykl pollowania nie mnoży wpisów w dzienniku", len(ponowne) == 1))
    return checks


def _testy_eskalacji():
    import escalation

    _use_temp_db()
    checks = []
    client = FakeClient()
    escalation.escalate_to_human(
        {"task_id": "PRJ-9", "title": f"Wymaga decyzji: {CZYSTY_TYTUL}", "project_id": "PRJ-1"},
        "bramka jakości nie przepuściła", client, assignee="Paweł")
    checks.append(("Eskalacja zadania eskalacyjnego ma dokładnie jeden przedrostek",
                   client.created[0]["title"] == f"Wymaga decyzji: {CZYSTY_TYTUL}"))
    return checks


def _testy_feedbacku():
    import task_feedback_requester as tfr

    checks = []
    zadania = [
        {"task_id": "T-1", "title": CZYSTY_TYTUL, "status": "done"},
        {"task_id": "T-2", "title": f"Wymaga decyzji: {CZYSTY_TYTUL}", "status": "done"},
        {"task_id": "T-3", "title": f"Feedback: {CZYSTY_TYTUL}", "status": "done"},
        {"task_id": "T-4", "title": CZYSTY_TYTUL, "status": "todo"},
    ]
    do_pytania = [t["task_id"] for t in tfr.find_tasks_needing_feedback(zadania, already_asked=set())]
    checks.append(("O feedback pytamy tylko do zwykłych, zamkniętych zadań", do_pytania == ["T-1"]))

    checks.append(("Feedback z pracy bota trafia do człowieka",
                   tfr._feedback_assignee({"assignee": "AI - Dev"}) == tfr.FEEDBACK_HUMAN_ALIAS))
    checks.append(("Brak przypisania -> feedback też do człowieka",
                   tfr._feedback_assignee({}) == tfr.FEEDBACK_HUMAN_ALIAS))
    checks.append(("Zadanie wykonane przez człowieka -> pytamy tę osobę",
                   tfr._feedback_assignee({"assignee": "Paweł"}) == "Paweł"))
    return checks


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = _testy_tytulow() + _testy_runnera() + _testy_eskalacji() + _testy_feedbacku()

    print("\n--- Wynik testu dymnego progu meta-zadań ---")
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
