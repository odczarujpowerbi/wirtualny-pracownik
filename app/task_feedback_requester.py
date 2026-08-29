"""
Prosi o feedback po zamknięciu zadania — komentarz + osobne zadanie w
Projectly + mail (PLAN-WDROZENIA.md sekcja 5, SKRYPTY.md kategoria L).

To jest odpowiedź na wprost zadane pytanie: "czy już istnieje skrypt, co
prosi o feedback i daje zadania ludziom w Projectly" — NIE istniał.
Najbliżej był `escalation.py`, ale to eskalacja DECYZJI przed wykonaniem,
nie prośba o feedback PO fakcie.

Narzędzia MCP (przez projectly_client): prośba o feedback to add_task_comment
(pytanie w wątku) + create_task (osobne zadanie feedbackowe powiązane z
oryginałem). Samą treść feedbacku człowiek/agent zapisuje potem w polu
`feedback` zadania przez update_task (client.set_task_feedback) — komentarze i
to pole są już dostępne w MCP (get_task_comments/add_task_comment,
update_task.feedback), co potwierdzono na żywo w tej sesji.

UCZCIWA GRANICA: Projectly nie ma pola "feedback POPROSZONY" (jest pole
`feedback` na treść, ale nie flaga, że o niego zapytano) — ten skrypt pilnuje
więc LOKALNIE (`runs/feedback_requested.json`), którym zadaniom już zadano
pytanie, żeby nie pytać w kółko przy każdym uruchomieniu. To stan lokalny per
maszyna (SKALOWANIE.md sekcja 2), nie substytut pola w Projectly.

Mail leci zgodnie z `config/email_safety.yaml` — dziś zawsze do człowieka
wewnątrz firmy (Paweł/Aldona), NIE bezpośrednio do assignee zadania.
"""

import json
from pathlib import Path

import meta_task_guard
from email_draft_generator import generate_draft
from projectly_client import get_client, is_ai_account_name

ASKED_PATH = Path(__file__).parent / "runs" / "feedback_requested.json"

# Feedback o wykonanej pracy ocenia CZŁOWIEK. Gdy zadanie wykonało konto AI
# (albo nie ma przypisania), prośba idzie do tego aliasu, a nie z powrotem do
# bota — inaczej zadanie feedbackowe wracało do runnera w get_new_tasks i
# napędzało pętlę meta-zadań (opis incydentu w meta_task_guard.py).
FEEDBACK_HUMAN_ALIAS = "pawel"

FEEDBACK_COMMENT = (
    "👋 Krótki feedback do tego zadania: ile realnie zajęło (jeśli różni się "
    "od estymacji), co było trudne, i czy zostały jakieś zaległości/podzadania "
    "do zamknięcia osobno? Odpowiedz komentarzem tutaj."
)


def _load_asked(path=ASKED_PATH):
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_asked(asked, path=ASKED_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(asked), ensure_ascii=False, indent=2), encoding="utf-8")


def find_tasks_needing_feedback(tasks, already_asked):
    """Zamknięte zadania, o które jeszcze nie pytaliśmy. Zadania META założone
    przez agenta (eskalacje, wcześniejsze prośby o feedback, kontynuacje) są
    pomijane — prośba o feedback do prośby o feedback tylko mnoży zadania i
    zaśmieca kolejkę człowieka."""
    return [
        t for t in tasks
        if t.get("status") == "done"
        and t["task_id"] not in already_asked
        and not meta_task_guard.is_meta_task(t)
    ]


def _feedback_assignee(task):
    """Kto ma odpowiedzieć na prośbę o feedback — patrz FEEDBACK_HUMAN_ALIAS."""
    assignee = task.get("assignee")
    if not assignee or is_ai_account_name(assignee):
        return FEEDBACK_HUMAN_ALIAS
    return assignee


def request_feedback_for_task(task, client=None, send_email=True):
    client = client or get_client()

    client.post_comment(task["task_id"], FEEDBACK_COMMENT)
    feedback_task_id = client.create_task(
        title=meta_task_guard.feedback_title(task["title"]),
        description=FEEDBACK_COMMENT,
        assigned_to=_feedback_assignee(task),
        parent_task_id=task["task_id"],
        project_id=task.get("project_id"),
        relation_type="kontynuacja",
    )

    email_result = None
    if send_email:
        email_result = generate_draft(
            "feedback_request",
            to=f"{task.get('assignee', 'zespol')}@wewnetrzny",
            action="send",
            tytul_zadania=task["title"],
            osoba=task.get("assignee", "?"),
            nadawca="Bot",
        )

    return {"task_id": task["task_id"], "feedback_task_id": feedback_task_id, "email": email_result}


def run_feedback_requests(client=None, send_email=True):
    client = client or get_client()
    tasks = client.list_tasks()
    already_asked = _load_asked()

    to_ask = find_tasks_needing_feedback(tasks, already_asked)
    results = []
    for task in to_ask:
        results.append(request_feedback_for_task(task, client=client, send_email=send_email))
        already_asked.add(task["task_id"])

    _save_asked(already_asked)
    return results


if __name__ == "__main__":
    for r in run_feedback_requests():
        print(r)
    print("\nDrugie uruchomienie (powinno być puste — te zadania już zapytane):")
    for r in run_feedback_requests():
        print(r)
