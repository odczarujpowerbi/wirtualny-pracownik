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

DWIE NAPRAWY PO ŻYWEJ ESKALACJI (zadanie "Feedback: Feedback: Analiza rozmów
1:1 czerwiec i wdrożenie zmian"):
1. Zadanie feedbackowe samo w sobie jest zadaniem, więc po domknięciu wpadało
   z powrotem do `find_tasks_needing_feedback` i dostawało własne zadanie
   feedbackowe ("Feedback: Feedback: ..."). Teraz zadania feedbackowe są
   pomijane — o prośbę o feedback nie prosimy o feedback.
2. Opis zadania feedbackowego niósł samo pytanie, bez ŻADNYCH danych zadania
   źródłowego (estymacja, czas realny, termin, dotychczasowe komentarze).
   Wykonawca — człowiek czy agent — nie miał z czego odpowiedzieć: albo zmyśli
   liczby, albo bramka jakości go odrzuci (i tak się stało). Teraz opis niesie
   fakty z Projectly, a braki nazywa wprost ("nie zarejestrowano"), więc
   uczciwa odpowiedź "tego nie ma w danych" jest zgodna z kryteriami akceptacji.
"""

import json
from pathlib import Path

from email_draft_generator import generate_draft
from mcp_client import MCPError
from projectly_client import get_client

ASKED_PATH = Path(__file__).parent / "runs" / "feedback_requested.json"

FEEDBACK_TITLE_PREFIX = "Feedback: "
MAX_COMMENTS_IN_BRIEF = 5
MAX_COMMENT_CHARS = 300
BRAK = "nie zarejestrowano"

FEEDBACK_COMMENT = (
    "👋 Krótki feedback do tego zadania: ile realnie zajęło (jeśli różni się "
    "od estymacji), co było trudne, i czy zostały jakieś zaległości/podzadania "
    "do zamknięcia osobno? Odpowiedz komentarzem tutaj."
)

FEEDBACK_QUESTIONS = (
    "DO ODPOWIEDZI (trzy punkty):\n"
    "1. Ile realnie zajęło i jak to się ma do estymacji.\n"
    "2. Co było trudne / co spowolniło.\n"
    "3. Co zostało niedomknięte (zaległości, podzadania do założenia osobno).\n"
)

NIE_ZMYSLAJ = (
    "ZASADA: opieraj się WYŁĄCZNIE na danych powyżej i na odpowiedzi osoby "
    f"wykonującej w komentarzach. Jeśli czegoś nie ma ({BRAK}), napisz to "
    "wprost — nie szacuj godzin i nie wymyślaj trudności."
)


def _load_asked(path=ASKED_PATH):
    if not path.exists():
        return set()
    return set(json.loads(path.read_text(encoding="utf-8")))


def _save_asked(asked, path=ASKED_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(asked), ensure_ascii=False, indent=2), encoding="utf-8")


def is_feedback_task(task):
    """Czy to zadanie samo jest prośbą o feedback (utworzoną przez ten skrypt).
    Bez tego filtra powstaje łańcuch 'Feedback: Feedback: ...' — każde domknięte
    zadanie feedbackowe generowało kolejne."""
    return str(task.get("title") or "").lstrip().startswith(FEEDBACK_TITLE_PREFIX)


def find_tasks_needing_feedback(tasks, already_asked):
    return [
        t for t in tasks
        if t.get("status") == "done"
        and t["task_id"] not in already_asked
        and not is_feedback_task(t)
    ]


def _pole(task, *klucze):
    """Wartość pierwszego niepustego klucza. Realny klient mapuje pola na
    snake_case (`estimated_hours`), mock oddaje surowy kształt Projectly
    (`estimatedHours`) — brief musi czytać oba."""
    for klucz in klucze:
        wartosc = task.get(klucz)
        if wartosc not in (None, "", []):
            return wartosc
    return None


def _fetch_comments(task_id, client):
    """Komentarze wątku zadania — to jedyne źródło 'co było trudne'. Błąd MCP
    nie może wywrócić prośby o feedback, ale nie może też zniknąć po cichu:
    logujemy i oznaczamy brak, żeby wykonawca wiedział, że lista jest niepełna."""
    try:
        return list(client.get_comments(task_id) or [])
    except MCPError as exc:
        print(f"[feedback] Nie udało się pobrać komentarzy {task_id}: {exc}")
        return None


def _linie_komentarzy(comments):
    if comments is None:
        return ["- Komentarze w wątku: nie udało się pobrać (patrz log przebiegu)"]
    if not comments:
        return ["- Komentarze w wątku: brak"]
    linie = [f"- Ostatnie komentarze w wątku ({len(comments)} łącznie):"]
    for tresc in comments[-MAX_COMMENTS_IN_BRIEF:]:
        jedna_linia = str(tresc).strip().replace("\n", " ")[:MAX_COMMENT_CHARS]
        linie.append(f"  • {jedna_linia}")
    return linie


def build_feedback_request_description(task, comments=None):
    """Opis zadania feedbackowego: fakty z zadania źródłowego + pytania.

    Zadanie feedbackowe trafia do osobnej kolejki (często do puli, czyli do
    agenta), gdzie NIE ma dostępu do zadania rodzica — więc wszystko, co
    potrzebne do odpowiedzi, musi być w opisie."""
    godziny_est = _pole(task, "estimated_hours", "estimatedHours")
    godziny_real = _pole(task, "actual_hours", "actualHours")
    linie = [
        f"Feedback do zamkniętego zadania „{task.get('title', '?')}” ({task['task_id']}).",
        "",
        "DANE Z PROJECTLY (stan na moment prośby):",
        f"- Zadanie źródłowe: {task['task_id']}",
        f"- Osoba odpowiedzialna: {_pole(task, 'assignee') or BRAK}",
        f"- Termin: {_pole(task, 'due_date', 'dueDate') or BRAK}",
        f"- Estymacja: {f'{godziny_est} h' if godziny_est is not None else BRAK}",
        f"- Czas realny (actualHours): {f'{godziny_real} h' if godziny_real is not None else BRAK}",
        f"- Data domknięcia: {_pole(task, 'completed_at', 'completedAt') or BRAK}",
        f"- Feedback już zapisany w zadaniu: {_pole(task, 'feedback') or BRAK}",
    ]
    linie += _linie_komentarzy(comments)
    linie += ["", FEEDBACK_QUESTIONS, NIE_ZMYSLAJ]
    return "\n".join(linie)


def request_feedback_for_task(task, client=None, send_email=True):
    client = client or get_client()

    # Komentarze POBIERAMY PRZED zadaniem pytania — inaczej brief cytowałby
    # nasze własne pytanie zamiast historii zadania.
    comments = _fetch_comments(task["task_id"], client)
    description = build_feedback_request_description(task, comments=comments)

    client.post_comment(task["task_id"], FEEDBACK_COMMENT)
    feedback_task_id = client.create_task(
        title=f"{FEEDBACK_TITLE_PREFIX}{task['title']}",
        description=description,
        assigned_to=_pole(task, "assignee") or "unassigned_pool",
        parent_task_id=task["task_id"],
        project_id=task.get("project_id"),
        relation_type="kontynuacja",
        # Bez goal/effect bramka jakości ocenia efekt względem pustego
        # oczekiwania (patrz docstring ProjectlyClient.create_task) — realnie
        # skończyło się to odrzuceniem i eskalacją do człowieka.
        expected_result=(
            f"Krótki feedback do zamkniętego zadania „{task.get('title', '?')}” "
            f"({task['task_id']}): czas realny vs estymacja, trudności, zaległości."
        ),
        acceptance_criteria=(
            "Odpowiedź ma trzy punkty (czas, trudności, zaległości), oparte na danych "
            "z opisu i komentarzach osoby wykonującej. Brak danych nazwany wprost "
            f"(„{BRAK}”) jest poprawną odpowiedzią; zmyślone godziny i trudności nie są."
        ),
    )

    email_result = None
    if send_email:
        # `or`, nie domyślna wartość .get: realny klient ZAWSZE zwraca klucz
        # 'assignee' (None przy braku przypisania), więc .get(..., 'zespol')
        # dawało adres "None@wewnetrzny".
        osoba = _pole(task, "assignee")
        email_result = generate_draft(
            "feedback_request",
            to=f"{osoba or 'zespol'}@wewnetrzny",
            action="send",
            tytul_zadania=task["title"],
            osoba=osoba or "?",
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
