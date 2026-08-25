"""
Prosi o feedback po zamknięciu zadania — komentarz + osobne zadanie w
Projectly + mail (PLAN-WDROZENIA.md sekcja 5, SKRYPTY.md kategoria L).

To jest odpowiedź na wprost zadane pytanie: "czy już istnieje skrypt, co
prosi o feedback i daje zadania ludziom w Projectly" — NIE istniał.
Najbliżej był `escalation.py`, ale to eskalacja DECYZJI przed wykonaniem,
nie prośba o feedback PO fakcie.

Narzędzia MCP (przez projectly_client): prośba o feedback to zbot_add_task_comment
(pytanie w wątku) + create_task (osobne zadanie feedbackowe powiązane z
oryginałem). Samą treść feedbacku człowiek/agent zapisuje potem w polu
`feedback` zadania przez update_task (client.set_task_feedback) — komentarze i
to pole są już dostępne w MCP (zbot_get_task_comments/zbot_add_task_comment,
update_task.feedback), co potwierdzono na żywo w tej sesji.

UCZCIWA GRANICA: Projectly nie ma pola "feedback POPROSZONY" (jest pole
`feedback` na treść, ale nie flaga, że o niego zapytano) — ten skrypt pilnuje
więc LOKALNIE (`runs/feedback_requested.json`), którym zadaniom już zadano
pytanie, żeby nie pytać w kółko przy każdym uruchomieniu. To stan lokalny per
maszyna (SKALOWANIE.md sekcja 2), nie substytut pola w Projectly. Zapis
DZIEJE SIĘ PO KAŻDYM zadaniu, nie raz na koniec pętli (żywy incydent
25.08.2026: pierwszy przebieg padł w środku na błędzie Graph/mailbox, zapis
na końcu nigdy nie nastąpił, więc KAŻDE kolejne uruchomienie próbowało od
zera — stąd fala zdublowanych komentarzy/zadań/maili za wszystkie zadania
"done" naraz).

Mail: DOMYŚLNIE WYŁĄCZONY (decyzja właściciela 25.08.2026) — prośba o feedback
PO fakcie nie jest sytuacją "czekam na decyzję człowieka", tylko informacją,
którą wystarczy mieć w komentarzu/zadaniu w Projectly do przeglądu, kiedy
wygodnie. Mail (gdy `send_email=True`) i tak zawsze leci zgodnie z
`config/email_safety.yaml` (dziś: tylko Paweł), NIE bezpośrednio do assignee.
"""

import json
from pathlib import Path

from email_draft_generator import generate_draft
from projectly_client import get_client

ASKED_PATH = Path(__file__).parent / "runs" / "feedback_requested.json"

FEEDBACK_COMMENT = (
    "👋 Krótki feedback do tego zadania: ile realnie zajęło (jeśli różni się "
    "od estymacji), co było trudne, i czy zostały jakieś zaległości/podzadania "
    "do zamknięcia osobno? Odpowiedz komentarzem tutaj."
)


def _load_asked(path=None):
    # path=None, nie path=ASKED_PATH — wartość domyślna parametru wiązałaby się
    # RAZ przy definicji funkcji; podmiana ASKED_PATH przez wywołującego (testy)
    # by wtedy nie miała żadnego efektu. Dynamiczny lookup wewnątrz ciała funkcji
    # poprawnie widzi bieżącą wartość globala.
    path = path or ASKED_PATH
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_asked(asked, path=None):
    path = path or ASKED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(asked), ensure_ascii=False, indent=2), encoding="utf-8")


def find_tasks_needing_feedback(tasks, already_asked):
    return [t for t in tasks if t.get("status") == "done" and t["task_id"] not in already_asked]


def request_feedback_for_task(task, client=None, send_email=False):
    client = client or get_client()

    client.post_comment(task["task_id"], FEEDBACK_COMMENT)
    feedback_task_id = client.create_task(
        title=f"Feedback: {task['title']}",
        description=FEEDBACK_COMMENT,
        assigned_to=task.get("assignee", "unassigned_pool"),
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


def run_feedback_requests(client=None, send_email=False):
    client = client or get_client()
    tasks = client.list_tasks()
    already_asked = _load_asked()

    to_ask = find_tasks_needing_feedback(tasks, already_asked)
    results = []
    for task in to_ask:
        results.append(request_feedback_for_task(task, client=client, send_email=send_email))
        already_asked.add(task["task_id"])
        # Zapis PO KAŻDYM zadaniu — jeśli coś dalej w liście padnie (sieć/Graph/
        # Projectly), to co już zrobione nie powtórzy się przy następnym uruchomieniu.
        _save_asked(already_asked)

    return results


if __name__ == "__main__":
    for r in run_feedback_requests():
        print(r)
    print("\nDrugie uruchomienie (powinno być puste — te zadania już zapytane):")
    for r in run_feedback_requests():
        print(r)
