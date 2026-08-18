"""
Test dymny ścieżki notatnika (intake lokalny obok Projectly). Pokrywa:
- parse_notebook: tagi ryzyka (!yellow/!red), ścieżka PBIP po @, pomijanie komentarzy,
- run_once: przetwarza NOWE zadania i dedupuje (drugi przebieg nic nie robi).

process_task jest podmieniany na atrapę (testujemy logikę intake'u, nie cały
pipeline — to szybkie i deterministyczne, bez wołania modelu). Używa tymczasowego
inboxa i pliku stanu. Wpina się automatycznie w self_check.py.
"""

import tempfile
from pathlib import Path

import notebook_intake
import runner_loop


def test_parse():
    text = (
        "# to jest komentarz — ignorowany\n"
        "\n"
        "Waliduj strukturę PBIP @ mock_data/sample_pbip\n"
        "Przejrzyj raport sprzedaży !yellow\n"
        "Zmień budżet kampanii !red\n"
    )
    tasks = notebook_intake.parse_notebook(text)
    assert len(tasks) == 3, tasks
    assert tasks[0]["action"] == "validate_pbip", tasks[0]
    assert tasks[0]["project_path"] == "mock_data/sample_pbip", tasks[0]
    assert tasks[0]["risk_level_hint"] == "green", tasks[0]
    assert tasks[1]["risk_level_hint"] == "yellow", tasks[1]
    assert tasks[1]["title"] == "Przejrzyj raport sprzedaży", tasks[1]
    assert tasks[2]["risk_level_hint"] == "red", tasks[2]
    print("OK  parse_notebook (tagi ryzyka, ścieżka @, pomijanie komentarzy)")


def test_run_once_dedupe():
    calls = []
    original = runner_loop.process_task
    runner_loop.process_task = lambda task, policy, routing, client: (
        calls.append(task["task_id"]) or {"task_id": task["task_id"], "status": "done"}
    )
    try:
        tmp = Path(tempfile.mkdtemp())
        inbox = tmp / "zadania.txt"
        inbox.write_text("Przejrzyj raport\nSprawdź plik INDEKA !yellow\n", encoding="utf-8")
        processed = tmp / "processed.json"

        first = notebook_intake.run_once(inbox_path=inbox, processed_path=processed)
        assert first["processed"] == 2, first
        assert len(calls) == 2, calls

        second = notebook_intake.run_once(inbox_path=inbox, processed_path=processed)
        assert second["processed"] == 0, second  # dedup: nic nowego
        assert len(calls) == 2, "process_task nie powinno być wywołane ponownie"
        print("OK  run_once przetwarza nowe zadania i dedupuje przy powtórnym przebiegu")
    finally:
        runner_loop.process_task = original


if __name__ == "__main__":
    test_parse()
    test_run_once_dedupe()
    print("\nWszystkie testy notatnika przeszły.")
