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
"""

import state_store


def escalate_to_human(task, reason, client, options=None, assignee="pawel"):
    """Tworzy w Projectly osobne zadanie przypisane do człowieka — NIE tylko
    komentarz (PLAN-WDROZENIA.md sekcja 4). Zwraca ID nowo utworzonego zadania."""
    from datetime import datetime, timezone

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
