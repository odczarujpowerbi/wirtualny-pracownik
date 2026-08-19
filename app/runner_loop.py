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

import bot_gustaw_bramka
import control
import cost_tracker
import executor
import heartbeat
import kill_switch
import live_status_publisher
import risk_classifier
import skill_usage_logger
import state_store
import task_router
import task_thinker
import validator_prompt
from escalation import escalate_to_human
from projectly_client import get_client

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
        state_store.log_decision(
            task_id, agent="pawel", decision="escalate",
            reason=f"prompt injection: {prompt_check['detail']}", now=now_iso(), event_type="escalation")
        status = "needs_approval"
        state_store.upsert_task(task_id, payload=task, status=status, assigned_to=owner, risk_level="red", now=now_iso())
        client.post_comment(task_id, _comment_escalated(owner, prompt_check["detail"]))
        client.update_status(task_id, status)
        return {"task_id": task_id, "risk": "red", "owner": owner, "status": status}

    action_type = HINT_TO_ACTION.get(task.get("risk_level_hint", "yellow"), "report_build")
    risk = risk_classifier.classify(action_type, policy)
    owner, confident = task_router.route_task(task["title"], routing)

    state_store.log_decision(
        task_id, agent="pawel", decision=f"risk={risk}",
        reason=f"action_type={action_type}, właściciel={owner}, pewność routingu={confident}",
        now=now, event_type="classified",
    )

    # Krok myślenia: model analizuje zadanie (Claude Code headless przez
    # `claude login`, albo SDK z ANTHROPIC_API_KEY jako fallback). Degraduje się
    # bez wywalania pętli, gdy model niedostępny (task_thinker.think).
    # action_type trafia do zadania, żeby Bożena (odbiór biznesowy) dobrała
    # właściwą warstwę kontekstu biznesowego per typ zadania.
    task["action_type"] = action_type

    thinking = task_thinker.think(task)
    state_store.record_event(task_id, "thinking", thinking.get("detail", ""), now_iso())

    # Realny worker, jeśli istnieje dla tego typu zadania (dziś: walidacja PBIP).
    # Gdy None — zostaje dotychczasowa ścieżka "sama klasyfikacja", nic nie udajemy.
    real = executor.execute(task)
    if real is not None:
        execution_result = {**real, "thinking": thinking,
                            "cost_usd": real.get("cost_usd", 0.0) + thinking.get("cost_usd", 0.0)}
        state_store.log_decision(
            task_id, agent="patrycja", decision=real["tool"],
            reason=real["acceptance_notes"], now=now_iso(),
            event_type="execution", cost_usd=real.get("cost_usd", 0.0),
        )
    else:
        execution_result = {
            "cost_usd": thinking.get("cost_usd", 0.0),
            "acceptance_notes": thinking.get("reasoning") or "Brak modelu — sama klasyfikacja/routing.",
            "thinking": thinking,
        }
    cost_tracker.record_cost(task_id, execution_result["cost_usd"])

    # Worker odmówił wykonania (np. ścieżka poza dozwolonym katalogiem roboczym) —
    # to zdarzenie bezpieczeństwa, eskalujemy wprost, nie przez bramkę jakości
    # (nie podajemy podejrzanej ścieżki dalej do botów).
    if real is not None and real.get("executed") is False:
        reason = real["acceptance_notes"]
        escalate_to_human(task, reason, client, assignee=owner)
        state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                 now=now_iso(), event_type="escalation")
        state_store.upsert_task(task_id, payload=task, status="needs_approval",
                                assigned_to=owner, risk_level=risk, now=now_iso())
        client.post_comment(task_id, _comment_escalated(owner, reason))
        client.update_status(task_id, "needs_approval")
        return {"task_id": task_id, "risk": risk, "owner": owner, "status": "needs_approval"}

    if risk == "red":
        reason = "Czerwona akcja — poza zakresem tego szkieletu, brak jeszcze zdefiniowanej bounded_red do sprawdzenia."
        escalate_to_human(task, reason, client, assignee=owner)
        state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                 now=now_iso(), event_type="escalation")
        status, comment = "needs_approval", _comment_escalated(owner, reason)

    elif risk == "green" and not _has_effect(execution_result):
        # Zielone bez realnego efektu (np. sam odczyt) — szybka ścieżka, bez bramki.
        state_store.log_decision(task_id, agent="pawel", decision="auto_done",
                                 reason="zielone bez efektu — auto, bez bramki", now=now_iso())
        status, comment = "done", _comment_green(owner)
        skill_usage_logger.log_usage(task_id, "risk_classifier", "success", "zielone bez efektu, auto")

    else:
        # Żółte ORAZ zielone z efektem (zrzut/plik/testy) przechodzą pełną bramkę
        # jakości (Gustaw): Bartek, Franek, Oskar, Bożena — zanim człowiek dostanie
        # odpowiedź jako gotową.
        gate = bot_gustaw_bramka.run_gate(task, execution_result)
        state_store.log_decision(
            task_id, agent="gustaw",
            decision="gate_passed" if gate["passed"] else "gate_failed",
            reason=gate["summary"], now=now_iso(), event_type="quality_gate")
        if gate["passed"]:
            status, comment = "done", _comment_gate_passed(owner, gate)
            skill_usage_logger.log_usage(task_id, "quality_gate", "success", gate["summary"])
        else:
            reason = _gate_failure_reason(gate)
            escalate_to_human(task, reason, client, assignee=owner)
            state_store.log_decision(task_id, agent="pawel", decision="escalate", reason=reason,
                                     now=now_iso(), event_type="escalation")
            status, comment = "needs_approval", _comment_escalated(owner, reason)
            skill_usage_logger.log_usage(task_id, "quality_gate", "failure", reason)

    state_store.upsert_task(task_id, payload=task, status=status, assigned_to=owner, risk_level=risk, now=now_iso())
    state_store.record_event(task_id, "status_set", status, now_iso())

    reasoning = execution_result.get("thinking", {}).get("reasoning")
    if reasoning:
        comment += "\n\n🧠 Analiza (Claude):\n" + reasoning

    client.post_comment(task_id, comment)
    client.update_status(task_id, status)

    return {"task_id": task_id, "risk": risk, "owner": owner, "status": status}


def _has_effect(execution_result):
    """Czy zadanie wytworzyło realny efekt do walidacji (zrzut, plik, testy,
    powtarzalny przebieg). Zielone bez efektu idą szybką ścieżką, z efektem —
    przez bramkę (decyzja usera: żółte i wyżej + zielone z efektem)."""
    return any(execution_result.get(k) for k in ("screenshot_path", "output_file", "functional_checks", "rerun"))


def _comment_green(owner):
    return f"✅ done\nCo zrobiono: klasyfikacja i routing (Faza 0-1 — bez realnego workera jeszcze).\nPrzypisano do: {owner}\n"


def _comment_gate_passed(owner, gate):
    return (
        f"✅ done (przeszło bramkę jakości: zgody {gate['approvals']}/{gate['required']})\n"
        f"{gate['summary']}\nPrzypisano do: {owner}\n"
    )


def _comment_escalated(owner, reason):
    return f"⚠️ needs_approval\nWymaga decyzji: tak — {reason}\nUtworzono osobne zadanie dla: {owner}\n"


def _gate_failure_reason(gate):
    concerns = "; ".join(gate["concerns"]) or "brak szczegółów"
    return f"Bramka jakości nie przepuściła zadania. {gate['summary']} Zastrzeżenia: {concerns}"


def run_once(client=None):
    if kill_switch.is_active():
        print(f"Kill switch aktywny ({kill_switch.reason()}) — runner nie podejmuje akcji.")
        return []
    if control.is_paused():
        print(f"PAUSE ({control.pause_reason()}) — runner nie podejmuje nowej pracy.")
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
