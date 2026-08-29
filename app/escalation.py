"""
Obieg eskalacji: zadanie dla człowieka -> komentarz -> weryfikacja ->
kontynuacja (PLAN-WDROZENIA.md sekcja 4, SKRYPTY.md kategoria C).
Zawiera escalate_to_human, human_response_validator i continuation_task_creator
w jednym module — w SKRYPTY.md to trzy osobne skrypty, tu trzymane razem,
bo dzielą ten sam mały kontrakt danych i łatwiej je testować spójnie.

Narzędzia MCP (przez projectly_client, config/projectly.yaml):
    escalate_to_human       -> create_task + link_tasks (type "eskalacja")
    human_response_validator -> get_comments (odczyt decyzji człowieka)
    continuation_task_creator -> create_task + link_tasks (type "kontynuacja")
Powiązania budują widoczny ciąg oryginał -> eskalacja -> kontynuacja
(get_task_relations), zamiast trzech luźnych zadań. Wymaga project_id z
zadania źródłowego (get_new_tasks niesie je w polu 'project_id').
"""

import state_store

# Przedrostek tytułu zadania eskalacyjnego i znacznik w jego opisie. Trzymane
# jako stałe, bo czyta je nie tylko ten moduł: runner_loop rozpoznaje po nich
# zadanie eskalacyjne wracające do kolejki i NIE bierze go do wykonania
# (is_escalation_task niżej).
ESCALATION_TITLE_PREFIX = "Wymaga decyzji: "
ESCALATION_MARKER = "[eskalacja-dla-czlowieka]"
ESCALATION_SKIP_REASON = (
    "Zadanie eskalacyjne (dla człowieka), bot go nie dekomponuje ani nie wykonuje."
)


def is_escalation_task(task):
    """Czy to zadanie jest ZADANIEM ESKALACYJNYM, czyli prośbą o decyzję
    człowieka, którą agent wcześniej sam założył (escalate_to_human).

    Po co: takie zadanie potrafi wrócić do kolejki agenta (np. gdy przypisanie
    nie rozwiązało się na osobę i Projectly przypisał je wg tokenu, czyli do
    konta AI). Bez tej bramki runner traktuje je jak zwykłą pracę: woła model,
    puszcza przez bramkę jakości, nie ma z czego zbudować wyniku, więc eskaluje
    JESZCZE RAZ i zamyka jako needs_approval. Cykl po cyklu, w kółko, kosztem
    modelu i lawiną komentarzy pod zadaniem, na które i tak czeka człowiek
    (żywy przebieg: 'Wymaga decyzji: Alert: stan maszyny wymaga sprawdzenia',
    osiem domknięć needs_approval pod rząd na tym samym zadaniu).

    Rozpoznajemy po znaczniku w opisie (zadania zakładane od teraz) ALBO po
    przedrostku tytułu (zadania eskalacyjne już leżące w Projectly, sprzed
    dołożenia znacznika, w tym to, które zapętliło runner). Zadania
    'Kontynuacja: ...' (continuation_task_creator) to praca DLA BOTA i celowo
    NIE są tu łapane."""
    if not isinstance(task, dict):
        return False
    if ESCALATION_MARKER in (task.get("description") or ""):
        return True
    title = (task.get("title") or "").lstrip()
    return title.lower().startswith(ESCALATION_TITLE_PREFIX.lower())


def escalate_to_human(task, reason, client, options=None, assignee="pawel"):
    """Tworzy w Projectly osobne zadanie przypisane do człowieka — NIE tylko
    komentarz (PLAN-WDROZENIA.md sekcja 4). Zwraca ID nowo utworzonego zadania."""
    from datetime import datetime, timezone

    title = f"{ESCALATION_TITLE_PREFIX}{task['title']}"
    description_lines = [
        ESCALATION_MARKER,
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
