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

O feedback pytamy WYŁĄCZNIE ludzi i wyłącznie o pracę merytoryczną — dwa
wykluczenia w find_tasks_needing_feedback, oba z żywego incydentu 29.08.2026
opisanego w feedback_task.py.
"""

import json
from pathlib import Path

import feedback_task
from email_draft_generator import generate_draft
from projectly_client import get_client

ASKED_PATH = Path(__file__).parent / "runs" / "feedback_requested.json"

FEEDBACK_COMMENT = feedback_task.FEEDBACK_PYTANIE


def _load_asked(path=ASKED_PATH):
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_asked(asked, path=ASKED_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(asked), ensure_ascii=False, indent=2), encoding="utf-8")


def find_tasks_needing_feedback(tasks, already_asked, ai_account_prefix=None):
    """Domknięte zadania, o które wypada zapytać o feedback.

    Dwa wykluczenia, oba naprawiają realną pętlę z 29.08.2026:

    1. Prośba o feedback SAMA nie dostaje prośby o feedback. Bez tego każde
       domknięcie dokładało poziom zagnieżdżenia ("Feedback: Feedback: ...")
       i mnożyło zadania bez końca.
    2. Zadania wykonane przez konto AI pomijamy. Pytanie "ile realnie zajęło,
       co było trudne" jest adresowane do CZŁOWIEKA, a prośba lądowała na
       koncie bota (assignee zadania źródłowego), skąd runner_loop brał ją z
       kolejki todo jako zwykłą pracę do wykonania. Nic nie tracimy: samoocenę
       ze swojej pracy agent zapisuje i tak w polu `feedback` zadania
       źródłowego (runner_loop._zapisz_feedback).
    """
    prefiks = ai_account_prefix or feedback_task.prefiks_konta_ai()
    return [
        t for t in tasks
        if t.get("status") == "done"
        and t["task_id"] not in already_asked
        and not feedback_task.czy_prosba_o_feedback(t)
        and not feedback_task.czy_wykonane_przez_konto_ai(t, prefiks)
    ]


def request_feedback_for_task(task, client=None, send_email=True):
    client = client or get_client()

    client.post_comment(task["task_id"], FEEDBACK_COMMENT)
    feedback_task_id = client.create_task(
        title=f"{feedback_task.FEEDBACK_TITLE_PREFIX}{task['title']}",
        # Opis niesie znacznik maszynowy — po nim (a nie po samym tytule)
        # poznajemy później, że to zadanie założył ten mechanizm.
        description=feedback_task.opis_prosby_o_feedback(),
        assigned_to=task.get("assignee") or "unassigned_pool",
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
