"""
Główna pętla: pobiera zadania, klasyfikuje ryzyko, rozdziela do właściciela,
uruchamia walidatory dla żółtych, sprawdza granice bounded red dla
czerwonych, eskaluje sporne/czerwone jako osobne zadania, publikuje status
na żywo, zapisuje stan i koszt (PLAN-WDROZENIA.md sekcje 1-4, 17, SKRYPTY.md
kategoria A). Sprawdza kill switch na starcie każdej iteracji.

Czego celowo brakuje (uczciwie): prawdziwych workerów (Power BI, CRM, Meta
Ads...). `execution_result` poniżej jest zaślepką reprezentującą "zadanie
odebrane, praca jeszcze niewykonana realnie" — wystarczającą, żeby
przetestować mechanikę klasyfikacji/walidacji/eskalacji, ale nie
zastępującą realnego workera z Fazy 3+.

Użycie:
    python runner_loop.py            # jeden przebieg, tryb mock
    python runner_loop.py --loop      # ciągła pętla (Ctrl+C żeby zatrzymać)
"""

import argparse
import sys
import time
from datetime import datetime, timezone

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env (patrz .env.example, bootstrap_init_secrets.py)

import cost_tracker
import heartbeat
import kill_switch
import live_status_publisher
import risk_classifier
import skill_usage_logger
import state_store
import task_router
import validator_prompt
from escalation import escalate_to_human
from projectly_client import get_client
from validator_pool import run_validators

HINT_TO_ACTION = {
    "green": "read_report",
    "yellow": "report_build",
    "red": "budget_change",
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def process_task(task, policy, routing, client):
    task_id = task["task_id"]
    now = now_iso()

    state_store.upsert_task(task_id, payload=task, status="planning", now=now)
    state_store.record_event(task_id, "task_received", task["title"], now)

    # Sprawdzenie bezpieczeństwa treści PRZED klasyfikacją ryzyka — wykryta
    # próba wstrzyknięcia eskaluje zawsze, niezależnie od koloru zadania
    # (dokumentacja bazowa 9.4: tekst zewnętrzny to dane, nie polecenie).
    prompt_check = validator_prompt.check_prompt_safety(task.get("title", ""))
    state_store.record_event(task_id, "prompt_safety_check", str(prompt_check), now_iso())
    if not prompt_check["safe"]:
        owner, _ = task_router.route_task(task["title"], routing)
        escalate_to_human(task, f"Wykryto podejrzaną treść: {prompt_check['detail']}", client, assignee=owner)
        status = "needs_approval"
        state_store.upsert_task(task_id, payload=task, status=status, assigned_to=owner, risk_level="red", now=now_iso())
        client.post_comment(task_id, _comment_escalated(owner, prompt_check["detail"]))
        client.update_status(task_id, status)
        return {"task_id": task_id, "risk": "red", "owner": owner, "status": status}

    action_type = HINT_TO_ACTION.get(task.get("risk_level_hint", "yellow"), "report_build")
    risk = risk_classifier.classify(action_type, policy)
    owner, confident = task_router.route_task(task["title"], routing)

    state_store.record_event(
        task_id, "classified", f"action_type={action_type} risk={risk} owner={owner} confident={confident}", now
    )

    # Zaślepka wykonania — patrz docstring modułu. Koszt=0, bo żaden model
    # jeszcze nie został wywołany na tym etapie (Faza 0-1).
    execution_result = {"cost_usd": 0.0, "acceptance_notes": "Faza 0-1: brak realnego workera, tylko klasyfikacja."}
    cost_tracker.record_cost(task_id, execution_result["cost_usd"])

    if risk == "green":
        status, comment = "done", _comment_green(owner)
        skill_usage_logger.log_usage(task_id, "risk_classifier", "success", "zielone, auto")

    elif risk == "yellow":
        requirements = risk_classifier.validator_requirements(action_type, policy)
        validation = run_validators(task, execution_result, requirements)
        if validation["auto_approved"]:
            status, comment = "done", _comment_yellow_approved(owner, validation)
            skill_usage_logger.log_usage(task_id, "validator_pool", "success", str(validation["agreement"]))
        else:
            reason = _validator_failure_reason(validation)
            escalate_to_human(task, reason, client, assignee=owner)
            status, comment = "needs_approval", _comment_escalated(owner, reason)
            skill_usage_logger.log_usage(task_id, "validator_pool", "failure", reason)

    else:  # red
        reason = "Czerwona akcja — poza zakresem tego szkieletu, brak jeszcze zdefiniowanej bounded_red do sprawdzenia."
        escalate_to_human(task, reason, client, assignee=owner)
        status, comment = "needs_approval", _comment_escalated(owner, reason)

    state_store.upsert_task(task_id, payload=task, status=status, assigned_to=owner, risk_level=risk, now=now_iso())
    state_store.record_event(task_id, "status_set", status, now_iso())

    client.post_comment(task_id, comment)
    client.update_status(task_id, status)

    return {"task_id": task_id, "risk": risk, "owner": owner, "status": status}


def _comment_green(owner):
    return f"✅ done\nCo zrobiono: klasyfikacja i routing (Faza 0-1 — bez realnego workera jeszcze).\nPrzypisano do: {owner}\n"


def _comment_yellow_approved(owner, validation):
    return (
        f"✅ done (auto-zatwierdzone: {validation['agreement']}/{validation['total']} walidatorów, "
        f"próg {validation['required']})\nPrzypisano do: {owner}\n"
    )


def _comment_escalated(owner, reason):
    return f"⚠️ needs_approval\nWymaga decyzji: tak — {reason}\nUtworzono osobne zadanie dla: {owner}\n"


def _validator_failure_reason(validation):
    failed = [r["detail"] for r in validation["results"] if not r["approved"]]
    return f"Zgoda {validation['agreement']}/{validation['total']} poniżej progu {validation['required']}. " + "; ".join(
        failed
    )


def run_once(client=None):
    if kill_switch.is_active():
        print(f"Kill switch aktywny ({kill_switch.reason()}) — runner nie podejmuje akcji.")
        return []

    policy = risk_classifier.load_policy()
    routing = task_router.load_routing()
    # client wstrzykiwany w testach (bootstrap_smoke_test wymusza mock, żeby test
    # mechanizmu był deterministyczny niezależnie od tego, czy live Projectly ma
    # akurat zadania). W produkcji None -> get_client() (mock albo realny wg .env).
    client = client or get_client()

    heartbeat.write_heartbeat(current_task_id=None)

    tasks = client.get_new_tasks()
    results = []
    for task in tasks:
        heartbeat.write_heartbeat(current_task_id=task["task_id"])
        results.append(process_task(task, policy, routing, client))

    heartbeat.write_heartbeat(current_task_id=None)
    live_status_publisher.publish(client, role="dev")

    daily_cost = cost_tracker.check_daily_limit()
    if daily_cost["over_limit"]:
        kill_switch.activate(
            f"Przekroczono dzienny limit kosztu: {daily_cost['total']} > {daily_cost['limit']} USD."
        )
        print("UWAGA: przekroczono dzienny limit kosztu, aktywowano kill switch.")

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Ciągła pętla zamiast jednego przebiegu")
    parser.add_argument("--interval", type=int, default=30, help="Sekundy między przebiegami w trybie --loop")
    args = parser.parse_args()

    if not args.loop:
        results = run_once()
        for r in results:
            print(r)
        return

    print(f"Runner w trybie ciągłym, interwał {args.interval}s. Ctrl+C żeby zatrzymać.")
    try:
        while True:
            if kill_switch.is_active():
                print(f"Kill switch aktywny ({kill_switch.reason()}) — zatrzymuję runner.")
                sys.exit(0)
            for r in run_once():
                print(r)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Zatrzymano ręcznie.")


if __name__ == "__main__":
    main()
