"""
Test dymny task_brief_builder. Sprawdza, że brief zawiera pola zadania, oś czasu
(z wstrzykniętych zdarzeń, pomijając techniczne) i wynik wykonania, a pełny prompt
myślenia dokłada instrukcję. Wstrzykuje events, więc nie dotyka bazy.

Użycie:
    python task_brief_builder_smoke_test.py
"""

import sys

import task_brief_builder


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    task = {"task_id": "PRJ-1", "title": "Waliduj PBIP INDEKA",
            "action_type": "validate_pbip", "expected_result": "Struktura poprawna",
            "acceptance_criteria": "Brak błędów TMDL"}
    events = [
        {"event_type": "task_received", "detail": "Waliduj PBIP INDEKA", "created_at": "t0"},
        {"event_type": "classified", "detail": "risk=green", "created_at": "t1"},
        {"event_type": "cost", "detail": "0.05 USD (claude)", "created_at": "t2"},
    ]
    exec_result = {"acceptance_notes": "Struktura poprawna: 12 plików TMDL.",
                   "screenshot_path": "runs/screenshots/x.png"}

    brief = task_brief_builder.build_brief(task, execution_result=exec_result, events=events)
    checks = [
        ("brief zawiera id zadania", "PRJ-1" in brief),
        ("brief zawiera tytuł", "Waliduj PBIP INDEKA" in brief),
        ("brief zawiera oś czasu (classified)", "classified" in brief),
        ("brief POMIJA zdarzenia techniczne (cost)", "0.05 USD" not in brief),
        ("brief zawiera wynik wykonania", "12 plików TMDL" in brief),
        ("brief zawiera ścieżkę zrzutu", "runs/screenshots/x.png" in brief),
    ]

    prompt = task_brief_builder.build_thinking_prompt(task, execution_result=exec_result, events=events)
    checks.append(("prompt myślenia dokłada instrukcję", "wirtualnym pracownikiem" in prompt and "PRJ-1" in prompt))

    # Zadanie bez task_id i bez events -> nie rzuca, zwraca sensowny brief.
    safe = task_brief_builder.build_brief({"title": "Bez id"})
    checks.append(("brief bez task_id -> nie rzuca", "Bez id" in safe))

    print("\n--- Wynik testu dymnego task_brief_builder ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
