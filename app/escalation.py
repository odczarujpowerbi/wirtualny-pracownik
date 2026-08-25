"""
Obieg eskalacji: zadanie dla człowieka -> komentarz -> weryfikacja ->
kontynuacja (PLAN-WDROZENIA.md sekcja 4, SKRYPTY.md kategoria C).
Zawiera escalate_to_human, human_response_validator i continuation_task_creator
w jednym module — w SKRYPTY.md to trzy osobne skrypty, tu trzymane razem,
bo dzielą ten sam mały kontrakt danych i łatwiej je testować spójnie.

Narzędzia MCP (przez projectly_client, config/projectly.yaml):
    escalate_to_human       -> create_task + zbot_link_tasks (type "eskalacja")
    human_response_validator -> get_comments (odczyt decyzji człowieka)
    continuation_task_creator -> create_task + zbot_link_tasks (type "kontynuacja")
Powiązania budują widoczny ciąg oryginał -> eskalacja -> kontynuacja
(zbot_get_task_relations), zamiast trzech luźnych zadań. Wymaga project_id z
zadania źródłowego (get_new_tasks niesie je w polu 'project_id').

Mail (decyzja właściciela 25.08.2026): escalate_to_human to JEDYNA sytuacja w
całym pipeline, gdzie bot faktycznie czeka na decyzję człowieka — więc to
JEDYNE miejsce, które wysyła mail (poprzednio żadne nie wysyłało; prośby o
feedback po fakcie w task_feedback_requester.py mają send_email=False
domyślnie, bo to nie jest sytuacja "czekam na akcję"). Adresat NIE jest
zaszyty tutaj — jedyne jawne miejsce to config/email_safety.yaml
(review_recipients), przez email_client.py; usunięcie/dodanie odbiorcy to
zmiana JEDNEGO configu, nie kodu. Fail-soft: błąd wysyłki nie blokuje
eskalacji (zadanie w Projectly to główny, trwały kanał — mail jest dodatkiem).
"""

from datetime import datetime, timezone

import email_client
import state_store


def _wyslij_powiadomienie_eskalacji(task, reason, new_task_id, assignee):
    try:
        subject = f"Decyzja potrzebna: {task.get('title', '')}"
        body = (
            f"Zadanie: {task.get('title', '')}\n"
            f"Co jest potrzebne: {reason}\n\n"
            f"Zadanie eskalacji w Projectly: {new_task_id}\n"
            f"Zadanie źródłowe: {task.get('task_id', '')}"
        )
        email_client.get_email_client().send_email(to=f"decyzja dla: {assignee}", subject=subject, body_text=body)
    except Exception as exc:  # noqa: BLE001 — powiadomienie dodatkowe, nie może ubić eskalacji
        print(f"[escalation] Powiadomienie mailowe nie powiodło się (eskalacja i tak zapisana w Projectly): {exc}")


def escalate_to_human(task, reason, client, options=None, assignee="pawel"):
    """Tworzy w Projectly osobne zadanie przypisane do człowieka — NIE tylko
    komentarz (PLAN-WDROZENIA.md sekcja 4) — i wysyła mail powiadomienia
    (adresaci: config/email_safety.yaml). Zwraca ID nowo utworzonego zadania."""
    title = f"Wymaga decyzji: {task['title']}"
    description_lines = [
        f"Zadanie źródłowe: {task['task_id']}",
        f"Co jest potrzebne: {reason}",
    ]
    if options:
        description_lines.append("Opcje: " + "; ".join(options))
    description = "\n".join(description_lines)

    new_id = client.create_task(
        title,
        description,
        assigned_to=assignee,
        parent_task_id=task["task_id"],
        project_id=task.get("project_id"),
        relation_type="eskalacja",
    )
    now = datetime.now(timezone.utc).isoformat()
    state_store.record_event(task["task_id"], "escalated_to_human", f"{new_id}: {reason}", now)
    _wyslij_powiadomienie_eskalacji(task, reason, new_id, assignee)
    return new_id


def human_response_validator(comment_text, expected_kind="decision"):
    """Sprawdza, czy komentarz człowieka faktycznie rozstrzyga sprawę
    (PLAN-WDROZENIA.md sekcja 4) — a nie tylko dopytuje albo jest niejasny.
    Prosta, deterministyczna heurystyka na start; w pełnej wersji może
    eskalować niejednoznaczne przypadki do modelu."""
    if not comment_text or not comment_text.strip():
        return {"sufficient": False, "reason": "Pusty komentarz."}

    text_lower = comment_text.lower().strip()

    if expected_kind == "decision":
        affirmative = ["zatwierdzam", "tak", "ok", "zgoda", "akceptuję"]
        negative = ["nie", "odrzucam", "stop"]
        if any(text_lower.startswith(word) for word in affirmative + negative):
            return {"sufficient": True, "reason": "Jednoznaczna decyzja rozpoznana."}
        return {
            "sufficient": False,
            "reason": "Komentarz nie zaczyna się od jednoznacznej decyzji (tak/nie/zatwierdzam/odrzucam).",
        }

    # expected_kind == "value" (np. brakująca informacja) — samo niepuste jest wystarczające na start
    if len(text_lower) < 3:
        return {"sufficient": False, "reason": "Odpowiedź zbyt krótka, żeby zawierać konkretną wartość."}
    return {"sufficient": True, "reason": "Odpowiedź zawiera treść dłuższą niż nic."}


def continuation_task_creator(original_task, human_decision_text, client):
    """Po pozytywnej weryfikacji odpowiedzi człowieka — tworzy nowe zadanie
    dla agenta z decyzją wbudowaną w kontekst (PLAN-WDROZENIA.md sekcja 4)."""
    from datetime import datetime, timezone

    title = f"Kontynuacja: {original_task['title']}"
    description = (
        f"Zadanie źródłowe: {original_task['task_id']}\n"
        f"Decyzja człowieka: {human_decision_text}\n"
        f"Kontynuuj wykonanie z tą decyzją wbudowaną w kontekst."
    )
    new_id = client.create_task(
        title,
        description,
        assigned_to="bot",
        parent_task_id=original_task["task_id"],
        project_id=original_task.get("project_id"),
        relation_type="kontynuacja",
    )
    now = datetime.now(timezone.utc).isoformat()
    state_store.record_event(original_task["task_id"], "continuation_created", new_id, now)
    return new_id
