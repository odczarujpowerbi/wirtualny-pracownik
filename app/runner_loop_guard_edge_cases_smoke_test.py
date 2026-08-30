"""
Test dymny: dokumentuje DWA znane, zaakceptowane kompromisy dwóch guardów w
runner_loop._process_task_core (audyt 27.08.2026). Ten test NIE zmienia
zachowania - potwierdza, że jest ono takie, jak właściciel świadomie
zaakceptował, żeby przyszła zmiana kodu złamała test zamiast po cichu
zmienić semantykę.

1) Guard ESCALATION_TITLE_PREFIX (linia ok. 166 w runner_loop.py) sprawdza
   WYŁĄCZNIE `task["title"].startswith("Wymaga decyzji: ")`. Nie sprawdza, czy
   zadanie faktycznie powstało przez escalate_to_human (np. nie patrzy na
   description, które escalate_to_human zawsze wypełnia frazą "Zadanie
   źródłowe:"). Więc zadanie wpisane RĘCZNIE przez człowieka w Projectly, które
   przypadkiem zaczyna się od tego samego prefiksu, też zostaje pominięte i
   oznaczone needs_approval bez dekompozycji/wykonania. To świadomy, bezpieczny
   kompromis: fałszywie dodatnie trafienie (rzadkie, bo prefiks jest dość
   specyficzny) kończy się jedynie tym, że zadanie i tak trafia do człowieka do
   decyzji - nie ginie, nie wykonuje się źle. Alternatywa (odróżnianie
   pochodzenia) jest gorsza: false negative (przepuszczenie prawdziwego
   zadania eskalacyjnego z powrotem do bota) odtwarzałby żywy bug 25-26.08.2026
   (tytuł mnożący się w kółko).

2) Guard already_subtask (linia ok. 210) sprawdza WYŁĄCZNIE
   `bool(task.get("parent_task_id"))`. Nie sprawdza, czy to pole ustawił
   task_decomposer.py, czy człowiek ręcznie połączył dwa zadania w Projectly
   (funkcja "Podzadania" widoczna w UI, ogólny mechanizm hierarchii Projectly,
   nie coś specyficznego dla dekompozycji fraktalnej). Każde zadanie z
   ustawionym parentTaskId pomija bramkę jakości ORAZ eskalację czerwonego
   ryzyka z zasady. To świadomie udokumentowany, ale WĄSKI zakres guardu -
   traktuje "ma rodzica" jako równoznaczne z "to podzadanie z dekompozycji",
   co nie jest prawdą dla każdego możliwego użycia pola parentTaskId w
   Projectly.

Bez sieci: task_decomposer.decide / task_thinker.think / agentic_worker.run /
bot_gustaw_bramka.run_gate / escalate_to_human są atrapami - w scenariuszu 1
RZUCAJĄ, jeśli zostaną wywołane (sam brak wyjątku dowodzi, że guard zadziałał
przed nimi); w scenariuszu 2 NAGRYWAJĄ wywołania (pusta lista dowodzi, że
bramka/eskalacja zostały pominięte).

Użycie:
    python runner_loop_guard_edge_cases_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import agentic_worker
import risk_classifier
import runner_loop
import state_store
import task_decomposer
import task_router
import task_thinker
from projectly_client import MockProjectlyClient

# Zadanie WPISANE RĘCZNIE PRZEZ CZŁOWIEKA (nie przez escalate_to_human) -
# description celowo NIE zawiera "Zadanie źródłowe:", więc widać, że guard nie
# patrzy na to pole, tylko na sam tytuł.
HUMAN_TASK_Z_PODOBNYM_TYTULEM = {
    "task_id": "T-HUMAN-LOOKALIKE", "title": "Wymaga decyzji: czy zmieniamy dostawcę hostingu",
    "expected_result": "", "acceptance_criteria": "",
    "description": "Pytanie od zarządu, nie eskalacja bota.",
    "risk_level_hint": "yellow", "project_id": "PROJ-1",
}

# Zadanie z parentTaskId ustawionym RĘCZNIE w Projectly (np. człowiek połączył
# dwa niezależne zadania jako "Podzadania" w UI) - nie przez task_decomposer.py.
MANUAL_PARENT_TASK = {
    "task_id": "T-MANUAL-PARENT", "title": "Zmień budżet kampanii na 800 zł",
    "expected_result": "", "acceptance_criteria": "", "description": "",
    "risk_level_hint": "red", "project_id": "PROJ-1",
    "parent_task_id": "T-INNE-ZADANIE-POLACZONE-RECZNIE",
}

THINKING_OK = {"ok": True, "reasoning": "Plan testowy.", "cost_usd": 0.0, "detail": "OK"}


def _wybuchnij(*a, **k):
    raise AssertionError("nie powinno się wywołać - guard tytułu musi zadziałać wcześniej")


def _test_tytul_od_czlowieka(tmp, checks):
    """Scenariusz 1: tytuł zaczynający się od prefiksu eskalacji, ale zadanie
    NIE pochodzi z escalate_to_human. Guard i tak je pomija - dokumentujemy to
    jako świadomy, bezpieczniejszy kompromis (konserwatywne pominięcie zamiast
    ryzyka przepuszczenia prawdziwej eskalacji)."""
    original_decide = task_decomposer.decide
    try:
        task_decomposer.decide = _wybuchnij

        client = MockProjectlyClient()
        client._created_tasks_path = tmp / "created1.json"
        client._comments_path = tmp / "comments1.json"
        client._feedback_path = tmp / "feedback1.json"
        client._agent_status_path = tmp / "agent_status1.json"

        policy = risk_classifier.load_policy()
        routing = task_router.load_routing()
        result = runner_loop.process_task(HUMAN_TASK_Z_PODOBNYM_TYTULEM, policy, routing, client)

        checks.append(("Zadanie od człowieka z tytułem-lookalike -> też needs_approval od razu",
                       result.get("status") == "needs_approval"))
        checks.append(("Też oznaczone escalation_skip (guard nie odróżnia pochodzenia)",
                       result.get("escalation_skip") is True))

        events = state_store.get_events("T-HUMAN-LOOKALIKE")
        checks.append(("Log zdarzeń zawiera escalation_task_skipped",
                       any(e["event_type"] == "escalation_task_skipped" for e in events)))
        checks.append(("task_decomposer.decide NIE wywołany (guard zadziałał przed nim)",
                       not any(e["event_type"] == "decomposition" for e in events)))
    finally:
        task_decomposer.decide = original_decide


def _test_parent_id_ustawiony_recznie(tmp, checks):
    """Scenariusz 2: parent_task_id ustawiony ręcznie w Projectly (nie przez
    task_decomposer). Guard already_subtask i tak pomija bramkę jakości ORAZ
    eskalację czerwonego ryzyka - dokumentujemy to jako znany, zaakceptowany,
    ale WĄSKI zakres guardu (patrz komentarz na górze pliku)."""
    original_think = task_thinker.think
    original_agentic_run = agentic_worker.run
    original_run_gate = runner_loop.bot_gustaw_bramka.run_gate
    original_escalate = runner_loop.escalate_to_human

    gate_calls, escalate_calls = [], []

    try:
        task_thinker.think = lambda task: THINKING_OK
        agentic_worker.run = lambda task, thinking, client=None, context=None: {
            "cost_usd": 0.0, "tool": "agentic_task", "executed": True,
            "acceptance_notes": "Zrobione (efekt testowy).",
            "functional_checks": [{"name": "test", "type": "nonempty_file", "target": "x"}],
            "output": {"folder": "x"},
        }
        runner_loop.bot_gustaw_bramka.run_gate = lambda *a, **k: gate_calls.append((a, k)) or {"passed": True}
        runner_loop.escalate_to_human = lambda *a, **k: escalate_calls.append((a, k))

        client = MockProjectlyClient()
        client._created_tasks_path = tmp / "created2.json"
        client._comments_path = tmp / "comments2.json"
        client._feedback_path = tmp / "feedback2.json"
        client._agent_status_path = tmp / "agent_status2.json"
        client.project_tasks_path = tmp / "tasks2.json"  # nie istnieje -> sibling_tasks() = []

        policy = risk_classifier.load_policy()
        routing = task_router.load_routing()
        result = runner_loop.process_task(MANUAL_PARENT_TASK, policy, routing, client)

        checks.append(("Zadanie z ręcznie połączonym parent_task_id, risk=red -> mimo to status done",
                       result.get("status") == "done"))
        checks.append(("bot_gustaw_bramka.run_gate NIE wywołane (guard nie sprawdza pochodzenia parenta)",
                       len(gate_calls) == 0))
        checks.append(("escalate_to_human NIE wywołane mimo risk=red",
                       len(escalate_calls) == 0))

        events = state_store.get_events("T-MANUAL-PARENT")
        checks.append(("Log zdarzeń zawiera powód pominięcia bramki/ryzyka z zasady",
                       any("bramka i ryzyko pominięte z zasady" in str(e["detail"]) for e in events)))
    finally:
        task_thinker.think = original_think
        agentic_worker.run = original_agentic_run
        runner_loop.bot_gustaw_bramka.run_gate = original_run_gate
        runner_loop.escalate_to_human = original_escalate


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")

    try:
        state_store.DB_PATH = tmp / "state.db"
        os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")

        _test_tytul_od_czlowieka(tmp, checks)
        _test_parent_id_ustawiony_recznie(tmp, checks)
    finally:
        state_store.DB_PATH = original_db_path
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu dymnego: znane edge case'y guardów (title-prefix, already_subtask) ---")
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
