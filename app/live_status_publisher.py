"""
Utrzymuje jeden, stały, nadpisywany wpis "status na żywo" per bot-rola w
Projectly (PLAN-WDROZENIA.md sekcja 2 — moduł analizy pracy w toku, nie
tylko zakończonych zadań). Harmonogram: co 1-2 min (config/schedule.yaml).

client.publish_status -> MCP post_agent_status (dedykowany, nadpisywany wiersz
statusu per rola — NIE strona dokumentacji projektu; PLAN-MONITOROWANIE-AGENTOW-
WIRTUALNY-PRACOWNIK.md). Transport (docelowy/legacy) w config/projectly.yaml
(live_status.transport) — przełączanie i mapowanie payloadu w projectly_client.py.
Kolejka zadań (processed_tasks/queued_tasks) NIE liczona ze state_store —
runner_loop.py woła process_task() synchronicznie w pętli `for`, więc żaden
task tam nigdy nie ma realnie statusu "queued" (od razu "planning"). Realną
listę tego, co właśnie przetworzono w tym przebiegu i co czeka na kolejny
poll (runner_loop.MAX_TASKS_PER_RUN), przekazuje wywołujący (runner_loop.py).
"""

import platform
from datetime import datetime, timezone
from pathlib import Path

import cost_tracker
import state_store
import task_decomposer
import watchdog

HEARTBEAT_PATH = Path(__file__).parent / "runs" / "heartbeat.json"

# Ile pozycji kolejki wysyłamy w payloadzie — bez limitu duży zaległy backlog
# rozdułby status na żywo (i wywołanie MCP) bez potrzeby; queue_depth i tak
# niesie prawdziwą, nieucięta liczbę.
MAX_QUEUE_ITEMS_IN_STATUS = 20


def build_status(role="dev", processed_tasks=None, queued_tasks=None):
    watchdog_result = watchdog.check()
    cost = cost_tracker.check_daily_limit()
    processed_tasks = processed_tasks or []
    queued_tasks = queued_tasks or []
    needs_approval = len(state_store.list_tasks(status="needs_approval"))

    current_task_id = None
    if HEARTBEAT_PATH.exists():
        import json

        hb = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        current_task_id = hb.get("current_task_id")

    return {
        "role": role,
        "machine": platform.node(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "current_task_id": current_task_id,
        # Ten przebieg run_once() jest sekwencyjny — "processed_tasks" to co
        # WŁAŚNIE skończyło się wykonywać (nie "trwa teraz", bo do chwili
        # publikacji jest już zamknięte), "queued_tasks" to co faktycznie
        # czeka na kolejny poll (odcięte przez MAX_TASKS_PER_RUN).
        "processed_this_cycle_count": len(processed_tasks),
        "processed_this_cycle": processed_tasks[:MAX_QUEUE_ITEMS_IN_STATUS],
        "queue_depth": len(queued_tasks),
        "queued_tasks": queued_tasks[:MAX_QUEUE_ITEMS_IN_STATUS],
        # Górny szacunek, nie pomiar — liczba zadań w kolejce razy budżet czasu
        # jednego subagenta (task_decomposer.TIME_BUDGET_MINUTES), bo tyle
        # maksymalnie może zająć KAŻDE z nich (patrz agentic_worker.AGENTIC_
        # TIMEOUT_SECONDS). Realnie zwykle szybciej — to celowo pesymistyczne.
        "estimated_minutes_to_clear_queue": len(queued_tasks) * task_decomposer.TIME_BUDGET_MINUTES,
        "needs_approval_count": needs_approval,
        "cost_today_usd": round(cost["total"], 4),
        "cost_limit_usd": cost["limit"],
        "health": "ok" if watchdog_result["status"] == "ok" else "alert",
    }


def publish(client, role="dev", processed_tasks=None, queued_tasks=None):
    status = build_status(role, processed_tasks, queued_tasks)
    client.publish_status(role, status)
    return status


if __name__ == "__main__":
    from projectly_client import get_client

    print(publish(get_client()))
