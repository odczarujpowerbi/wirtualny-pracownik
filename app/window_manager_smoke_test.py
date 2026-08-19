"""
Test dymny window_manager. Sprawdza logikę dopasowania okien i łagodną
degradację bez backendu — nie zależy od tego, czy pygetwindow/pywinauto są
zainstalowane (używa mało prawdopodobnego tytułu, więc wynik jest deterministyczny).

Użycie:
    python window_manager_smoke_test.py
"""

import sys

import window_manager

_UNLIKELY = "zzz_okno_ktore_nie_istnieje_9f3a1c"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        ("_match: fragment, case-insensitive", window_manager._match("Power BI Desktop", "power bi")),
        ("_match: brak dopasowania", window_manager._match("Excel", "power bi") is False),
        ("_match: pusty tytuł -> False", window_manager._match("", "x") is False),
        ("_match: puste zapytanie -> False", window_manager._match("Okno", "") is False),
        ("list_windows: zwraca listę", isinstance(window_manager.list_windows(), list)),
        ("find_window: nieistniejące -> None", window_manager.find_window(_UNLIKELY) is None),
        ("get_bounds: nieistniejące -> None", window_manager.get_bounds(_UNLIKELY) is None),
    ]

    focus = window_manager.focus_window(_UNLIKELY)
    checks.append(("focus_window: nieistniejące -> ok False + detail",
                   focus["ok"] is False and bool(focus["detail"])))

    avail = window_manager.available()
    checks.append(("available: zwraca {available, backend}",
                   set(avail.keys()) == {"available", "backend"}))

    print("\n--- Wynik testu dymnego window_manager ---")
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
