"""
Krok 8 bootstrapu (SKALOWANIE.md sekcja 4): test dymny przed przekazaniem
nowego komputera do pracy. Przepuszcza jedno testowe zadanie przez pełen
cykl, sprawdza heartbeat i reakcję kill switcha. Odpowiednik scenariuszy
T-01/T-07 z planu testów dokumentacji bazowej, jako checklist odbioru
maszyny.

Użycie:
    python bootstrap_smoke_test.py
"""

import sys

import kill_switch
import runner_loop
import watchdog
from projectly_client import MockProjectlyClient


def run():
    checks = []

    # Test dymny sprawdza MECHANIZM na danych testowych (mock), więc wymuszamy
    # MockProjectlyClient — niezależnie od tego, czy maszyna ma już wpisany token
    # do realnego Projectly. Realny Projectly może mieć akurat 0 zadań todo dla
    # konta AI tej roli, co NIE znaczy, że runner jest zepsuty.
    mock_client = MockProjectlyClient()

    print("1/3 — pełny cykl zadań przez runner_loop.run_once() (dane testowe/mock)...")
    results = runner_loop.run_once(client=mock_client)
    checks.append(("Runner przetworzył zadania z mock_data", len(results) > 0))

    print("2/3 — świeżość heartbeat...")
    hb_check = watchdog.check()
    checks.append(("Heartbeat świeży", hb_check["status"] == "ok"))

    print("3/3 — reakcja kill switcha...")
    kill_switch.activate("Test dymny bootstrapu.")
    blocked_results = runner_loop.run_once(client=mock_client)
    kill_switch.deactivate()
    checks.append(("Kill switch blokuje wykonanie", blocked_results == []))

    print("\n--- Wynik testu dymnego ---")
    all_passed = True
    for name, passed in checks:
        symbol = "✅" if passed else "❌"
        print(f"{symbol} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł — nie przekazuj komputera do pracy bez wyjaśnienia dlaczego.")
        sys.exit(1)

    print("\nWszystkie testy przeszły. Komputer gotowy do rejestracji (bootstrap_register.py).")


if __name__ == "__main__":
    run()
