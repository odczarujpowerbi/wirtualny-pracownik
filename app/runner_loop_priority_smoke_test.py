"""
Test dymny dwóch mechanizmów priorytetowej kolejki (żądanie właściciela
29.08.2026, patrz runner_loop.py):

  1. `_wybierz_partie_wg_priorytetu` — z całej pobranej kolejki do partii
     tego przebiegu wchodzi TYLKO najwyższy OBECNY priorytet, capped
     MAX_TASKS_PER_RUN; nadmiar tego poziomu i wszystkie niższe poziomy
     wracają do `deferred`.
  2. Zadanie wchodzące do partii dostaje status "w trakcie" w Projectly
     NATYCHMIAST po przyjęciu — PRZED realną pracą — ale ścieżki, które
     kończą się wcześniej (zadanie eskalacyjne, duplicate guard) nie mają
     tego statusu w ogóle wywoływać.

Zero sieci: state_store izolowany (tymczasowa baza), model degradowany
atrapą "niedostępny" (jak w bootstrap_smoke_test.py), klient Projectly to
lekka atrapa nagrywająca wywołania update_status w kolejności.

Użycie:
    python runner_loop_priority_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import projectly_client
import runner_loop
import state_store
import task_thinker

_BRAK_MODELU_ASK = {
    "available": False, "text": None, "source": None,
    "detail": "runner_loop_priority_smoke_test: model celowo wyłączony.",
}
_BRAK_MODELU_THINK = {
    "available": False, "ok": False, "reasoning": None,
    "detail": "runner_loop_priority_smoke_test: model celowo wyłączony.",
    "cost_usd": 0.0, "source": None,
}


class _FakeClient:
    """Atrapa Projectly — nagrywa TYLKO to, co ten test sprawdza (kolejność
    update_status). Reszta (post_comment/publish_status/feedback) to no-op,
    tak jak realny klient bez skonfigurowanego MCP by się zachował."""

    def __init__(self):
        self.update_status_calls = []
        self.comments = []

    def update_status(self, task_id, status):
        self.update_status_calls.append((task_id, status))
        return True

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True

    def publish_status(self, role, payload):
        return True

    def default_admin_project_id(self):
        return None


def _zadanie(task_id, title, priority=None):
    return {"task_id": task_id, "title": title, "priority": priority,
            "project_id": "PROJ-1", "assignee": "bot"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- 1. effective_priority: fallback na brak/nienumeryczną wartość,
    # ale priority=0 (PARKING) NIE jest podbijane (żywy bug 29.08.2026 —
    # `priority or default` traktowałby 0 jako falsy). ---
    checks.append(("effective_priority: brak pola -> BIEŻĄCE (4)",
                   projectly_client.effective_priority({}) == 4))
    checks.append(("effective_priority: priority=0 (PARKING) zostaje 0, nie 4",
                   projectly_client.effective_priority({"priority": 0}) == 0))
    checks.append(("effective_priority: wartość nienumeryczna -> fallback",
                   projectly_client.effective_priority({"priority": "wysoki"}) == 4))

    # --- 2. _wybierz_partie_wg_priorytetu: tylko najwyższy obecny poziom,
    # capped MAX_TASKS_PER_RUN; nadmiar TEGO poziomu + wszystkie niższe -> deferred. ---
    tasks = (
        [_zadanie(f"T-5-{i}", f"Priorytet 5 #{i}", priority=5) for i in range(6)]
        + [_zadanie("T-4", "Priorytet 4 (bieżące)", priority=4)]
        + [_zadanie("T-3", "Priorytet 3 (backlog)", priority=3)]
        + [_zadanie("T-0", "Priorytet 0 (parking)", priority=0)]
    )
    batch, deferred = runner_loop._wybierz_partie_wg_priorytetu(tasks)
    checks.append(("_wybierz_partie_wg_priorytetu: partia = MAX_TASKS_PER_RUN (5)",
                   len(batch) == runner_loop.MAX_TASKS_PER_RUN))
    checks.append(("_wybierz_partie_wg_priorytetu: partia to WYŁĄCZNIE priorytet 5",
                   all(t["priority"] == 5 for t in batch)))
    checks.append(("_wybierz_partie_wg_priorytetu: deferred = nadmiar priorytetu 5 + niższe poziomy (4)",
                   len(deferred) == 4 and {t["task_id"] for t in deferred} == {"T-5-5", "T-4", "T-3", "T-0"}))

    # --- 3. Gdy najwyższy obecny poziom ma MNIEJ zadań niż limit — cała
    # partia wchodzi, reszta (niższe poziomy) i tak zaczeka. ---
    tasks_malo = [_zadanie("A", "a", priority=4), _zadanie("B", "b", priority=4),
                  _zadanie("C", "c", priority=3), _zadanie("D", "d", priority=0)]
    batch2, deferred2 = runner_loop._wybierz_partie_wg_priorytetu(tasks_malo)
    checks.append(("_wybierz_partie_wg_priorytetu: poziom z <limit zadań -> cała partia wchodzi",
                   {t["task_id"] for t in batch2} == {"A", "B"}))
    checks.append(("_wybierz_partie_wg_priorytetu: niższe poziomy zaczekają",
                   {t["task_id"] for t in deferred2} == {"C", "D"}))

    # --- 4. Brak pola priority (None) domyślnie BIEŻĄCE (4) — bije jawny
    # priorytet 0 (parking), ale przegrywa z jawnym priorytetem 5. ---
    tasks_mieszane = [_zadanie("BEZ-PRIORYTETU", "brak pola"), _zadanie("PARKING", "parking", priority=0)]
    batch3, deferred3 = runner_loop._wybierz_partie_wg_priorytetu(tasks_mieszane)
    checks.append(("_wybierz_partie_wg_priorytetu: brak priorytetu (fallback 4) wygrywa z jawnym parkingiem (0)",
                   {t["task_id"] for t in batch3} == {"BEZ-PRIORYTETU"}
                   and {t["task_id"] for t in deferred3} == {"PARKING"}))

    checks.append(("_wybierz_partie_wg_priorytetu: pusta kolejka -> pusta partia i pusty deferred",
                   runner_loop._wybierz_partie_wg_priorytetu([]) == ([], [])))

    # --- 5. Status "w trakcie" NATYCHMIAST po przyjęciu, PRZED realną pracą —
    # ale nie dla ścieżek kończących się wcześniej (eskalacja/duplicate). ---
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_ask_model = task_thinker.ask_model
    original_think = task_thinker.think

    try:
        state_store.DB_PATH = tmp / "state.db"
        task_thinker.ask_model = lambda prompt, caller=None: _BRAK_MODELU_ASK
        task_thinker.think = lambda task, caller=None: _BRAK_MODELU_THINK

        policy = __import__("risk_classifier").load_policy()
        routing = __import__("task_router").load_routing()

        # 5a. Zadanie normalne (odczyt, hint zielony, bez efektu) -> auto_done,
        # ale MUSI dostać "in_progress" ZANIM dostanie finalne "done".
        client_ok = _FakeClient()
        zadanie_ok = _zadanie("T-OK", "Sprawdź logi serwera z tego tygodnia", priority=5)
        wynik = runner_loop._process_task_core(zadanie_ok, policy, routing, client_ok)
        statusy = [s for (_, s) in client_ok.update_status_calls]
        checks.append(("_process_task_core: zadanie normalne kończy się statusem 'done'",
                       wynik["status"] == "done"))
        checks.append(("_process_task_core: 'in_progress' wysłane PRZED finalnym statusem",
                       statusy[:1] == ["in_progress"] and "done" in statusy[1:]))

        # 5b. Zadanie eskalacyjne (tytuł z ESCALATION_TITLE_PREFIX) — bot je
        # tylko potwierdza jako needs_approval, NIGDY nie woła update_status
        # (ani "in_progress", ani nic innego) — to zadanie dla człowieka.
        client_esk = _FakeClient()
        from escalation import ESCALATION_TITLE_PREFIX
        zadanie_esk = _zadanie("T-ESK", f"{ESCALATION_TITLE_PREFIX}Coś dla człowieka", priority=0)
        wynik_esk = runner_loop._process_task_core(zadanie_esk, policy, routing, client_esk)
        checks.append(("_process_task_core: zadanie eskalacyjne -> needs_approval, BRAK update_status",
                       wynik_esk["status"] == "needs_approval" and client_esk.update_status_calls == []))

        # 5c. Duplicate guard: to samo task_id już ma lokalny status 'done'
        # sprzed chwili -> drugi przebieg ma pominąć zadanie CAŁKOWICIE,
        # bez wysyłania "in_progress" (inaczej zadanie już zamknięte migałoby
        # z powrotem na "w trakcie" bez żadnej kolejnej korekty statusu).
        client_dup = _FakeClient()
        zadanie_dup = _zadanie("T-DUP", "Sprawdź logi serwera drugi raz", priority=5)
        runner_loop._process_task_core(zadanie_dup, policy, routing, client_dup)
        client_dup.update_status_calls.clear()
        wynik_dup2 = runner_loop._process_task_core(zadanie_dup, policy, routing, client_dup)
        checks.append(("_process_task_core: duplicate guard -> BRAK drugiego 'in_progress'",
                       wynik_dup2.get("duplicate") is True and client_dup.update_status_calls == []))
    finally:
        task_thinker.ask_model = original_ask_model
        task_thinker.think = original_think
        state_store.DB_PATH = original_db_path

    print("\n--- Wynik testu dymnego runner_loop (priorytet kolejki + wczesny status) ---")
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
