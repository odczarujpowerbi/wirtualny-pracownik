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

import json
import platform
from datetime import datetime, timedelta, timezone
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

# Ile ostatnich decyzji agentów (state_store.get_recent_decisions) pokazujemy —
# tylko z ostatniej godziny (żądanie właściciela 25.08.2026: chce widzieć,
# JAKIE decyzje zapadły, nie tylko jakie zadania przeleciały).
RECENT_DECISIONS_WINDOW = timedelta(hours=1)
MAX_RECENT_DECISIONS_IN_STATUS = 10


def _skonfigurowany_interwal(job_name, domyslny):
    """Realny interval_seconds z (żywego) config/schedule.yaml, jeśli da się
    go odczytać — inaczej `domyslny`. Używane, żeby payload niósł PRAWDZIWY
    interwał odpytywania danej roli (żywy incydent 25.08.2026: dashboard
    Projectly pokazywał "offline" rolom o rzadszym niż 30s cyklu — freshness
    trzeba liczyć wobec RZECZYWISTEGO interwału per rola, nie jednego globalnego
    progu). Fail-soft: błąd odczytu configu nie może zablokować publikacji statusu."""
    try:
        import job_scheduler

        for job in job_scheduler.load_schedule():
            if job["name"] == job_name:
                return job.get("interval_seconds", domyslny)
    except Exception:  # noqa: BLE001 — to tylko metadana pomocnicza dla UI
        pass
    return domyslny


def _ostatnie_decyzje():
    """Decyzje agentów z ostatniej godziny (state_store.get_recent_decisions),
    najnowsza pierwsza, krótko streszczone — żądanie właściciela 25.08.2026:
    "nie mam informacji jakie decyzje zostały podjęte"."""
    granica = datetime.now(timezone.utc) - RECENT_DECISIONS_WINDOW
    decyzje = []
    for d in state_store.get_recent_decisions(limit=200):
        try:
            if datetime.fromisoformat(d["created_at"]) < granica:
                break  # DESC po id ~ DESC po czasie — dalej będzie tylko starzej
        except (TypeError, ValueError):
            continue
        decyzje.append(f"{d['agent']}: {d['decision']}" + (f" — {d['reason'][:80]}" if d.get("reason") else ""))
        if len(decyzje) >= MAX_RECENT_DECISIONS_IN_STATUS:
            break
    return decyzje


def _needs_approval_count(client):
    """Realna liczba NIEROZSTRZYGNIĘTYCH eskalacji w Projectly (tytuł zaczyna
    się "Wymaga decyzji:", status != "done") — NIE licznik lokalny ze
    state_store (żywy incydent 25.08.2026: 341 wpisów lokalnie, w tym 336 z
    MOCK pipeline'u notebook_intake.py, ktore w ogole nie istnieja w Projectly
    — user zobaczyl 341 "zadan do decyzji" bez ZADNEGO realnego pokrycia).
    Fail-soft: błąd/mock bez pełnej listy -> 0, nie wywala publikacji statusu."""
    try:
        tasks = client.list_tasks()
    except Exception:  # noqa: BLE001 — dodatkowa metadana, nie może ubić publikacji
        return 0
    return sum(1 for t in tasks if (t.get("title") or "").startswith("Wymaga decyzji:") and t.get("status") != "done")


def build_status(role="dev", processed_tasks=None, queued_tasks=None, client=None, detail=None):
    watchdog_result = watchdog.check()
    cost = cost_tracker.check_daily_limit()
    processed_tasks = processed_tasks or []
    queued_tasks = queued_tasks or []
    needs_approval = _needs_approval_count(client) if client is not None else 0

    current_task_id = None
    if HEARTBEAT_PATH.exists():
        hb = json.loads(HEARTBEAT_PATH.read_text(encoding="utf-8"))
        current_task_id = hb.get("current_task_id")

    return {
        "role": role,
        "machine": platform.node(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        # Realny interwał odpytywania (patrz _skonfigurowany_interwal) — do
        # liczenia freshness/online wobec WŁASNEGO cyklu tej roli, nie jednego
        # globalnego progu.
        "update_interval_seconds": _skonfigurowany_interwal("runner_loop", 30),
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
        "recent_decisions": _ostatnie_decyzje(),
        "cost_today_usd": round(cost["total"], 4),
        "cost_limit_usd": cost["limit"],
        "health": "ok" if watchdog_result["status"] == "ok" else "alert",
        # "working" jeśli ten przebieg realnie coś zrobił/ma coś do zrobienia —
        # NIE zawsze "idle" jak dotąd (żywy incydent 25.08.2026: user widział
        # "bezczynny" mimo realnej pracy — build_status() nigdy nie ustawiało
        # 'status', więc _map_status_payload zawsze wpisywało domyślne "idle").
        "status": "working" if (processed_tasks or queued_tasks) else "idle",
        # detail (29.08.2026, docs/MCP-STATUS-I-KOSZTY.md sekcja 1): dłuższy opis
        # zdarzenia, pokazywany po rozwinięciu w monitoringu. `detail` jawnie
        # podane przez wywołującego wygrywa; inaczej domyślny, zbudowany z
        # processed_tasks (id + tytuł każdego przetworzonego zadania w tym
        # cyklu) — bez tego jedynym śladem PO CO był ten przebieg jest skrócony
        # `message` (obcięty do 500 znaków, patrz _map_status_payload).
        "detail": detail if detail is not None else (
            "; ".join(f"{t.get('task_id', '?')}: {str(t.get('title') or '?')[:60]}" for t in processed_tasks)
            or None
        ),
    }


def publish(client, role="dev", processed_tasks=None, queued_tasks=None, detail=None):
    status = build_status(role, processed_tasks, queued_tasks, client=client, detail=detail)
    client.publish_status(role, status)
    return status


if __name__ == "__main__":
    from projectly_client import get_client

    print(publish(get_client()))
