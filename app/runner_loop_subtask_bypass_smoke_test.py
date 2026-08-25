"""
Test dymny: podzadanie z dekompozycji (task["parent_task_id"] ustawione)
pomija bramkę jakości ORAZ eskalację czerwonego ryzyka z zasady (decyzja
właściciela 25.08.2026 — podzadania są z natury słabo opisane, ocena samej
treści im nie służy). Kończy się status "done" mimo risk="red" i realnego
efektu wykonania, BEZ wywołania bot_gustaw_bramka.run_gate i escalate_to_human.

Bez sieci: task_thinker.think i agentic_worker.run są atrapami.

Użycie:
    python runner_loop_subtask_bypass_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import agentic_worker
import risk_classifier
import runner_loop
import state_store
import task_router
import task_thinker
from projectly_client import MockProjectlyClient

SUBTASK = {"task_id": "T-SUB-1", "title": "Zmień budżet kampanii na 500 zł",
           "expected_result": "", "acceptance_criteria": "", "description": "",
           "risk_level_hint": "red", "project_id": "PROJ-1", "parent_task_id": "T-RODZIC"}

THINKING_OK = {"ok": True, "reasoning": "Plan testowy.", "cost_usd": 0.0, "detail": "OK"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    original_think = task_thinker.think
    original_agentic_run = agentic_worker.run
    original_run_gate = runner_loop.bot_gustaw_bramka.run_gate
    original_escalate = runner_loop.escalate_to_human

    gate_calls, escalate_calls = [], []

    try:
        state_store.DB_PATH = tmp / "state.db"
        os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")

        task_thinker.think = lambda task: THINKING_OK
        agentic_worker.run = lambda task, thinking, client=None: {
            "cost_usd": 0.0, "tool": "agentic_task", "executed": True,
            "acceptance_notes": "Zrobione (efekt testowy).",
            "functional_checks": [{"name": "test", "type": "nonempty_file", "target": "x"}],
            "output": {"folder": "x"},
        }
        runner_loop.bot_gustaw_bramka.run_gate = lambda *a, **k: gate_calls.append((a, k)) or {"passed": True}
        runner_loop.escalate_to_human = lambda *a, **k: escalate_calls.append((a, k))

        client = MockProjectlyClient()
        client._created_tasks_path = tmp / "created.json"
        client._comments_path = tmp / "comments.json"
        client._feedback_path = tmp / "feedback.json"
        client._agent_status_path = tmp / "agent_status.json"
        client.project_tasks_path = tmp / "tasks.json"  # nie istnieje -> sibling_tasks() = []

        policy = risk_classifier.load_policy()
        routing = task_router.load_routing()
        result = runner_loop.process_task(SUBTASK, policy, routing, client)

        checks.append(("Podzadanie z risk=red i realnym efektem -> status done",
                       result.get("status") == "done"))
        checks.append(("bot_gustaw_bramka.run_gate NIE wywołane dla podzadania", len(gate_calls) == 0))
        checks.append(("escalate_to_human NIE wywołane dla podzadania", len(escalate_calls) == 0))

        events = state_store.get_events("T-SUB-1")
        checks.append(("Log zdarzeń zawiera powód pominięcia bramki/ryzyka z zasady",
                       any("bramka i ryzyko pominięte z zasady" in str(e["detail"]) for e in events)))

        comments = client._load(client._comments_path, default={})
        checks.append(("Komentarz na podzadaniu wspomina, że to podzadanie bez bramki",
                       "T-SUB-1" in comments and any("podzadanie" in c for c in comments["T-SUB-1"])))
    finally:
        task_thinker.think = original_think
        agentic_worker.run = original_agentic_run
        runner_loop.bot_gustaw_bramka.run_gate = original_run_gate
        runner_loop.escalate_to_human = original_escalate
        state_store.DB_PATH = original_db_path
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu dymnego: podzadanie pomija bramkę i eskalację ---")
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
