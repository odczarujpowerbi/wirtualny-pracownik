"""
Odbiera odpowiedź człowieka na eskalację i wraca z nią do bota — domyka pętlę
eskalacja->kontynuacja (escalation.py), która dziś kończyła się w połowie:
`escalation.continuation_task_creator`/`human_response_validator` istniały,
ale NIC ich nie wywoływało poza testami (żywa luka znaleziona 29.08.2026,
żądanie właściciela: "gdy człowiek zrobi swoje zadanie... wraca z feedbackiem
do bota i może wykonywać zadanie dalej").

Cykl (jak kacper_monitor.py — kursor stanu per rola w runs/, żeby proces
każdej roli pilnował TYLKO swoich eskalacji):
    1. Zadania z tytułem ESCALATION_TITLE_PREFIX, przypisane do WŁASNEGO konta
       AI (own_account_name — WS1, 29.08.2026: bot nie czyta cudzych eskalacji,
       nawet dla tego mechanizmu).
    2. status == "done", jeszcze nieobsłużone -> ostatni komentarz człowieka
       (get_comments) przez human_response_validator:
       - wystarczający -> continuation_task_creator (nowe zadanie dla bota,
         wisi pod tym samym zadaniem GŁÓWNYM co eskalacja — escalation.py WS2a),
         oznaczone jako obsłużone (nie dubluje kontynuacji przy kolejnym cyklu).
       - niewystarczający -> komentarz z prośbą o doprecyzowanie (dedup per
         dzień — nie spamuje przy każdym cyklu, dopóki człowiek nie odpowie
         inaczej).
    3. status != "done" i termin (`due_date`) minął -> jedno przypomnienie
       (dedup per dzień, ten sam wzorzec co kacper_monitor/system_health_monitor).

UCZCIWA GRANICA (żywa niespójność kontraktu, znaleziona przy pisaniu tego
modułu, NIE naprawiona tu — poza zakresem tego zadania): MockProjectlyClient.
list_tasks() zwraca fixture SUROWO (klucz "dueDate"), podczas gdy realny
ProjectlyClient.list_tasks() mapuje przez _map_task do "due_date" — ten sam
task wygląda inaczej w mock i na produkcji. _termin_minal() niżej czyta OBA
warianty defensywnie, żeby ten moduł działał poprawnie na obu, ale to tylko
obejście objawu, nie naprawa źródła (digest_generator.py ma dokładnie ten sam
problem, patrz jego split_tasks/_parse_date - zgłoszone właścicielowi osobno).
"""

import json
from datetime import date, datetime, timezone
from pathlib import Path

import env_bootstrap
import state_store
from escalation import ESCALATION_TITLE_PREFIX, continuation_task_creator, human_response_validator
from projectly_client import get_client, own_account_name

CLARIFY_COMMENT = (
    "🤔 Twoja odpowiedź nie brzmi jak jednoznaczna decyzja (np. 'zatwierdzam'/'nie'/'ok') "
    "— doprecyzuj, proszę, żebym mógł kontynuować pracę."
)
OVERDUE_COMMENT = (
    "⏰ Przypomnienie: termin tego zadania minął, a nadal czeka na Twoją decyzję."
)


def _state_path_for_role(role):
    suffix = "" if role == "dev" else f"_{role}"
    return Path(__file__).parent / "runs" / f"escalation_watcher_state{suffix}.json"


def _load_state(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"resolved": {}, "asked_clarify": {}, "overdue_reminded": {}}


def _save_state(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _today_key():
    return datetime.now(timezone.utc).date().isoformat()


def _termin_minal(task, today=None):
    """Czy due_date zadania minął. Czyta 'due_date' (kontrakt realnego klienta,
    _map_task) ORAZ 'dueDate' (surowy klucz fixture w MockProjectlyClient.
    list_tasks — patrz zastrzeżenie w docstringu modułu) — brak pola w obu
    wariantach -> nie uznajemy za przeterminowane (fail-closed, nie zgadujemy)."""
    today = today or date.today()
    surowy = task.get("due_date") or task.get("dueDate")
    if not surowy:
        return False
    try:
        return datetime.strptime(surowy, "%Y-%m-%d").date() < today
    except ValueError:
        return False


def _wlasne_eskalacje(tasks, own_account):
    """Zadania eskalacyjne WŁASNEGO konta AI (WS1, 29.08.2026: ten mechanizm
    też nie ma czytać/działać na cudzych eskalacjach). own_account=None (brak
    configu/roli) -> filtr pomijany, jak w task_feedback_requester.py."""
    return [
        t for t in tasks
        if (t.get("title") or "").startswith(ESCALATION_TITLE_PREFIX)
        and (own_account is None or t.get("assignee") == own_account)
    ]


def _obsluz_rozstrzygniete(task, client, state):
    task_id = task["task_id"]
    if task_id in state["resolved"]:
        return None
    komentarze = client.get_comments(task_id)
    ostatni = komentarze[-1] if komentarze else ""
    wynik = human_response_validator(ostatni)
    now = datetime.now(timezone.utc).isoformat()
    if wynik["sufficient"]:
        nowy_id = continuation_task_creator(task, ostatni, client)
        state["resolved"][task_id] = {"handled_at": now, "continuation_task_id": nowy_id}
        return {"kind": "continuation", "task_id": task_id, "continuation_task_id": nowy_id}
    klucz_dedup = f"{task_id}:{_today_key()}"
    if klucz_dedup not in state["asked_clarify"]:
        client.post_comment(task_id, CLARIFY_COMMENT)
        state["asked_clarify"][klucz_dedup] = True
        return {"kind": "clarify_requested", "task_id": task_id}
    return None


def _obsluz_przeterminowane(task, client, state):
    task_id = task["task_id"]
    if not _termin_minal(task):
        return None
    klucz_dedup = f"{task_id}:{_today_key()}"
    if klucz_dedup in state["overdue_reminded"]:
        return None
    client.post_comment(task_id, OVERDUE_COMMENT)
    state["overdue_reminded"][klucz_dedup] = True
    return {"kind": "overdue_reminder", "task_id": task_id}


def run_once(client=None, state_path=None):
    client = client or get_client()
    role = env_bootstrap._current_role()
    state_path = state_path or _state_path_for_role(role)
    state = _load_state(state_path)

    tasks = client.list_tasks()
    eskalacje = _wlasne_eskalacje(tasks, own_account_name(role))

    zdarzenia = []
    for task in eskalacje:
        if task.get("status") == "done":
            wynik = _obsluz_rozstrzygniete(task, client, state)
        else:
            wynik = _obsluz_przeterminowane(task, client, state)
        if wynik:
            state_store.record_event(
                task["task_id"], f"escalation_watcher:{wynik['kind']}",
                json.dumps(wynik, ensure_ascii=False), datetime.now(timezone.utc).isoformat())
            zdarzenia.append(wynik)

    _save_state(state, state_path)
    return {"scanned": len(eskalacje), "events": zdarzenia}


if __name__ == "__main__":
    print(run_once())
