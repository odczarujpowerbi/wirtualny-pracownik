"""
Test dymny risk_hint. Sprawdza, że treść zadania wyznacza kolor: akcje
nieodwracalne/zewnętrzne -> red, czysty odczyt -> green, reszta -> yellow.

Użycie:
    python risk_hint_smoke_test.py
"""

import sys

import risk_hint


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        ("wysyłka maila do klienta -> red",
         risk_hint.hint_from_task({"title": "Wyślij raport mailem do klienta INDEKA"}) == "red"),
        ("zmiana budżetu -> red",
         risk_hint.hint_from_task({"title": "Zwiększ budżet kampanii o 20%"}) == "red"),
        ("czysty odczyt/analiza -> green",
         risk_hint.hint_from_task({"title": "Sprawdź i przeanalizuj plik źródłowy"}) == "green"),
        ("action validate_pbip -> green (read-only z definicji)",
         risk_hint.hint_from_task({"action": "validate_pbip", "title": "cokolwiek"}) == "green"),
        ("neutralne zadanie -> yellow",
         risk_hint.hint_from_task({"title": "Przepięcie źródła w raporcie Magnapharm"}) == "yellow"),
        ("red bije green w tym samym tekście",
         risk_hint.hint_from_task({"title": "Sprawdź raport i wyślij go do klienta"}) == "red"),
    ]

    print("\n--- Wynik testu dymnego risk_hint ---")
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
