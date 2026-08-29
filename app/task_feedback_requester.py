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

DWIE RZECZY, KTÓRE TU NIE DZIAŁAŁY (żywy incydent: zadanie
"Feedback: Feedback: Dodanie godzin do aplikacji" poszło na eskalację do
człowieka, bo bramka jakości go nie przepuściła):
1. Zadanie feedbackowe samo trafiało pod prośbę o feedback, gdy je zamknięto —
   stąd podwojony prefiks i pytanie o feedback do pytania o feedback. Teraz
   `is_feedback_task` odsiewa je w `find_tasks_needing_feedback`.
2. Opis zadania był samym pytaniem, bez ŻADNYCH danych i bez celu/kryteriów
   odbioru. Wykonawca (człowiek albo agent) nie miał z czego napisać feedbacku,
   a bramka oceniała efekt względem pustego oczekiwania — dokładnie ten
   scenariusz, przed którym ostrzega docstring `projectly_client.create_task`.
   Teraz opis niesie estymację, czas realny i wyliczone odchylenie prosto z
   Projectly, a `create_task` dostaje expected_result i acceptance_criteria.
"""

import json
from pathlib import Path

from email_draft_generator import generate_draft
from projectly_client import get_client

ASKED_PATH = Path(__file__).parent / "runs" / "feedback_requested.json"

FEEDBACK_PREFIX = "Feedback: "

FEEDBACK_COMMENT = (
    "👋 Krótki feedback do tego zadania: ile realnie zajęło (jeśli różni się "
    "od estymacji), co było trudne, i czy zostały jakieś zaległości/podzadania "
    "do zamknięcia osobno? Odpowiedz komentarzem tutaj."
)

FEEDBACK_EXPECTED_RESULT = (
    "Komentarz z feedbackiem do zadania źródłowego: czas realizacji vs estymacja, "
    "co było trudne, jakie zostały zaległości. Zapisany w wątku zadania źródłowego "
    "albo w jego polu `feedback`."
)

FEEDBACK_ACCEPTANCE_CRITERIA = (
    "1. Odniesienie do czasu realizacji względem estymacji (liczby są w opisie zadania).\n"
    "2. Wskazanie, co było trudne albo co spowolniło pracę.\n"
    "3. Lista zaległości/podzadań do zamknięcia osobno albo wprost napisane, że ich nie ma.\n"
    "4. Jeśli któregoś punktu NIE da się odpowiedzieć z danych dostępnych w opisie "
    "(bo wie to tylko wykonawca), poprawną odpowiedzią jest napisanie wprost, czego "
    "brakuje i od kogo trzeba to dobrać. To jest wykonanie zadania, nie jego brak."
)

BRAK_DANYCH = "(brak w Projectly)"


def _load_asked(path=ASKED_PATH):
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_asked(asked, path=ASKED_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(asked), ensure_ascii=False, indent=2), encoding="utf-8")


def is_feedback_task(task):
    """Czy to zadanie samo jest prośbą o feedback. Bez tego filtra zamknięcie
    zadania feedbackowego rodziło kolejne ("Feedback: Feedback: ...") i tak w
    kółko — każdy taki poziom jest coraz bardziej bez treści."""
    return str(task.get("title", "")).startswith(FEEDBACK_PREFIX)


def find_tasks_needing_feedback(tasks, already_asked):
    return [
        t for t in tasks
        if t.get("status") == "done" and t["task_id"] not in already_asked and not is_feedback_task(t)
    ]


def _as_hours(value):
    """Godziny z Projectly bywają liczbą albo tekstem ("6", "6.5"). None gdy brak
    albo gdy nie da się odczytać jako liczby — wtedy pokazujemy BRAK_DANYCH
    zamiast zmyślać wartość."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _format_hours(value):
    hours = _as_hours(value)
    return BRAK_DANYCH if hours is None else f"{hours:g} h"


def format_deviation(estimated, actual):
    """Odchylenie czasu realnego od estymacji, policzone deterministycznie tutaj —
    żeby wykonawca feedbacku dostał liczbę, a nie zadanie do policzenia."""
    est = _as_hours(estimated)
    act = _as_hours(actual)
    if est is None or act is None:
        return f"{BRAK_DANYCH} — potrzebna estymacja ORAZ czas realny"
    diff = act - est
    if est == 0:
        return f"{diff:+g} h (brak estymacji odniesienia)"
    return f"{diff:+g} h ({diff / est * 100:+.0f}%)"


def build_feedback_brief(task):
    """Opis zadania feedbackowego: najpierw dane z Projectly, potem pytania.
    Puste pola są nazwane wprost jako brakujące, żeby wykonawca wiedział, czego
    ma dobrać, zamiast zgadywać."""
    return "\n".join([
        f'Feedback do zadania "{task.get("title", "?")}" ({task.get("task_id", "?")}).',
        "",
        "Dane z Projectly na moment prośby:",
        f"- Wykonawca: {task.get('assignee') or BRAK_DANYCH}",
        f"- Estymacja: {_format_hours(task.get('estimated_hours'))}",
        f"- Czas realny: {_format_hours(task.get('actual_hours'))}",
        f"- Odchylenie: {format_deviation(task.get('estimated_hours'), task.get('actual_hours'))}",
        f"- Termin: {task.get('due_date') or BRAK_DANYCH}",
        f"- Zamknięte: {task.get('completed_at') or BRAK_DANYCH}",
        "",
        FEEDBACK_COMMENT,
        "",
        "Czego nie ma w powyższych danych (trudności, otwarte zaległości) — to wie "
        "tylko wykonawca. Jeśli nie masz jak tego dobrać, napisz to wprost zamiast "
        "wypełniać szablon pustymi zdaniami.",
    ])


def request_feedback_for_task(task, client=None, send_email=True):
    client = client or get_client()
    # .get(klucz, domyślne) tu nie zadziała: _map_task ZAWSZE ustawia 'assignee',
    # więc przy braku przypisania wartością jest None, a nie brak klucza.
    assignee = task.get("assignee") or "unassigned_pool"

    client.post_comment(task["task_id"], FEEDBACK_COMMENT)
    feedback_task_id = client.create_task(
        title=f"{FEEDBACK_PREFIX}{task['title']}",
        description=build_feedback_brief(task),
        assigned_to=assignee,
        parent_task_id=task["task_id"],
        project_id=task.get("project_id"),
        relation_type="kontynuacja",
        expected_result=FEEDBACK_EXPECTED_RESULT,
        acceptance_criteria=FEEDBACK_ACCEPTANCE_CRITERIA,
    )

    email_result = None
    if send_email:
        email_result = generate_draft(
            "feedback_request",
            to=f"{assignee}@wewnetrzny",
            action="send",
            tytul_zadania=task["title"],
            osoba=assignee,
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
