"""
Test dymny: zadanie utworzone przez escalate_to_human (tytuł "Wymaga decyzji:
...") NIGDY nie jest dekomponowane/wykonywane/eskalowane ponownie przez bota —
niezależnie od tego, do kogo jest faktycznie przypisane w Projectly. Żywy bug
25-26.08.2026: takie zadania wracały do kolejki bota i tytuł narastał w kółko
("Wymaga decyzji: Wymaga decyzji: Wymaga decyzji: ..."), mnożąc podzadania i
eskalacje bez końca (posprzątane ręcznie w projekcie LDIT, patrz commit z
naprawą escalation.py + runner_loop.py z 26.08.2026).

Bez sieci: task_decomposer.decide/task_thinker.think/agentic_worker.run/
bot_gustaw_bramka.run_gate są atrapami, które RZUCAJĄ jeśli zostaną wywołane —
sam fakt braku wyjątku dowodzi, że guard zadziałał PRZED nimi.

Użycie:
    python runner_loop_escalation_skip_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import risk_classifier
import runner_loop
import state_store
import task_decomposer
import task_router
from projectly_client import MockProjectlyClient

ESCALATION_TASK = {"task_id": "T-ESK-SKIP", "title": "Wymaga decyzji: Zrób research konkurencji",
                   "expected_result": "", "acceptance_criteria": "", "description": "",
                   "risk_level_hint": "yellow", "project_id": "PROJ-1"}


def _wybuchnij(*a, **k):
    raise AssertionError("nie powinno się wywołać dla zadania eskalacyjnego")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    original_decide = task_decomposer.decide

    try:
        state_store.DB_PATH = tmp / "state.db"
        os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")
        task_decomposer.decide = _wybuchnij

        client = MockProjectlyClient()
        client._created_tasks_path = tmp / "created.json"
        client._comments_path = tmp / "comments.json"
        client._feedback_path = tmp / "feedback.json"
        client._agent_status_path = tmp / "agent_status.json"

        policy = risk_classifier.load_policy()
        routing = task_router.load_routing()
        result = runner_loop.process_task(ESCALATION_TASK, policy, routing, client)

        checks.append(("Zadanie eskalacyjne -> status needs_approval od razu",
                       result.get("status") == "needs_approval"))
        checks.append(("Zadanie eskalacyjne -> oznaczone escalation_skip", result.get("escalation_skip") is True))

        events = state_store.get_events("T-ESK-SKIP")
        checks.append(("Log zdarzeń zawiera escalation_task_skipped",
                       any(e["event_type"] == "escalation_task_skipped" for e in events)))
        checks.append(("Log zdarzeń NIE zawiera decomposition (task_decomposer nigdy wywołany)",
                       not any(e["event_type"] == "decomposition" for e in events)))

        stan = state_store.get_task("T-ESK-SKIP")
        checks.append(("Stan w bazie: status needs_approval", stan["status"] == "needs_approval"))

        # Drugi przebieg (symulacja ponownego pollingu tego samego zadania) —
        # dalej krótkie cięcie, żadnego wybuchu z atrapy.
        result2 = runner_loop.process_task(ESCALATION_TASK, policy, routing, client)
        checks.append(("Powtórne przetworzenie: dalej needs_approval, bez wybuchu atrapy",
                       result2.get("status") == "needs_approval"))
    finally:
        task_decomposer.decide = original_decide
        state_store.DB_PATH = original_db_path
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu dymnego: zadania eskalacyjne nie są przetwarzane ponownie ---")
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
