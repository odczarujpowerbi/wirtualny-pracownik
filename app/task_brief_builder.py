"""
Budowa "briefu zadania" — kontekst, który decydent (główny model) dostaje ZA
KAŻDYM razem, żeby zawsze miał kontekst zadania i problemu, niezależnie od tego,
ile czasu minęło i czy proces się restartował.

Naprawia wątpliwość #9 z audytu: task_thinker wołał model z surowymi 4 polami
zadania, w neutralnym katalogu, bez historii. Tu rekonstruujemy kontekst z
trwałego źródła prawdy (state_store.events), a nie z pamięci procesu:
  - pola zadania (co i po co),
  - oś czasu dotychczasowych zdarzeń/decyzji (co już się wydarzyło),
  - podsumowanie ostatniego wykonania, jeśli jest.

Reset kontekstu jest naturalny i bezpieczny: nowe zadanie = nowy brief, zero
przecieku z poprzedniego. Domknięty blok (status done/needs_approval) runner
oznacza zdarzeniem 'block_closed' — brief kolejnych zadań go nie wciąga.
"""

import kontekst_firmy
import state_store

MAX_FIELD_CHARS = 1500
MAX_EVENTS = 12
_SKIP_EVENT_TYPES = {"cost", "status_set", "heartbeat"}


def _trim(value):
    text = str(value) if value not in (None, "") else "(brak)"
    return text[:MAX_FIELD_CHARS]


def _timeline_lines(events, max_events):
    """Ostatnie istotne zdarzenia zadania, najstarsze->najnowsze, zwięźle."""
    meaningful = [e for e in events if e.get("event_type") not in _SKIP_EVENT_TYPES]
    recent = meaningful[-max_events:]
    lines = []
    for e in recent:
        detail = (e.get("detail") or "").strip().replace("\n", " ")
        lines.append(f"  - [{e.get('event_type')}] {detail[:200]}")
    return lines


def build_brief(task, execution_result=None, events=None, max_events=MAX_EVENTS):
    """Zwięzły, czytelny brief zadania. `events` można wstrzyknąć (test); domyślnie
    czytane z trwałej historii state_store po task_id."""
    task_id = task.get("task_id", "(bez id)")
    if events is None:
        events = state_store.get_events(task_id) if task.get("task_id") else []

    lines = [
        f"KONTEKST ZADANIA {task_id}",
        f"Tytuł: {_trim(task.get('title'))}",
        f"Typ akcji: {_trim(task.get('action_type') or task.get('action'))}",
        f"Oczekiwany rezultat: {_trim(task.get('expected_result'))}",
        f"Kryteria akceptacji: {_trim(task.get('acceptance_criteria'))}",
        f"Opis: {_trim(task.get('description'))}",
    ]

    timeline = _timeline_lines(events, max_events)
    if timeline:
        lines.append("Dotychczasowy przebieg (oś czasu):")
        lines.extend(timeline)

    if execution_result:
        notes = (execution_result.get("acceptance_notes") or "").strip()
        if notes:
            lines.append("Wynik ostatniego wykonania:")
            lines.append(f"  {notes[:MAX_FIELD_CHARS]}")
        if execution_result.get("screenshot_path"):
            lines.append(f"Zrzut ekranu efektu: {execution_result['screenshot_path']}")

    return "\n".join(lines)


def build_thinking_prompt(task, execution_result=None, events=None):
    """Pełny prompt kroku myślenia: instrukcja + realia firmy + brief zadania.

    Kontekst firmy stoi PRZED briefem, bo decyduje, jak zadanie w ogóle rozumieć:
    to samo polecenie "przygotuj materiał o Power BI" znaczy co innego dla marki
    szkoleniowej (sprzedajemy wiedzę) i wdrożeniowej (sprzedajemy gotowy efekt)."""
    brief = build_brief(task, execution_result=execution_result, events=events)
    tekst_zadania = " ".join(str(task.get(k) or "") for k in ("title", "description"))
    kontekst = kontekst_firmy.zbuduj(tekst_zadania)
    return (
        "Jesteś wirtualnym pracownikiem. Przeanalizuj zadanie w jego pełnym "
        "kontekście i odpowiedz zwięźle (maks. 8 zdań), w punktach:\n"
        "1. Co rozumiesz, że trzeba zrobić.\n"
        "2. Proponowany plan/podejście (kroki).\n"
        "3. Ryzyka albo czego brakuje, żeby to wykonać.\n"
        "4. Rekomendacja: automatycznie czy potrzebna decyzja człowieka.\n\n"
        + (f"{kontekst}\n\n" if kontekst else "")
        + f"{brief}\n"
    )


if __name__ == "__main__":
    demo_task = {"task_id": "DEMO-1", "title": "Waliduj PBIP INDEKA",
                 "expected_result": "Struktura poprawna", "action_type": "validate_pbip"}
    demo_events = [
        {"event_type": "task_received", "detail": "Waliduj PBIP INDEKA", "created_at": "t0"},
        {"event_type": "classified", "detail": "risk=green", "created_at": "t1"},
    ]
    print(build_thinking_prompt(demo_task, events=demo_events))
