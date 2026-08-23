"""
Test dymny cost_estimator. Sprawdza, że koszt Claude Code jest NIEZEROWy (żeby
kill switch liczył wolumen), lokalny model = 0, a SDK skaluje się z liczbą znaków.

Użycie:
    python cost_estimator_smoke_test.py
"""

import sys

import cost_estimator


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    cc = cost_estimator.estimate_call("claude_code")
    small = cost_estimator.estimate_call("anthropic_sdk", input_chars=400, output_chars=100)
    big = cost_estimator.estimate_call("anthropic_sdk", input_chars=40000, output_chars=10000)

    # Koszt zależny od roli (model_registry.py) — poprzednio SDK liczyło ZAWSZE
    # wg cennika Opusa niezależnie od realnie użytego modelu (błąd: stare stałe
    # $15/$75 za milion, 3x wyższe niż prawdziwa cena Opusa 5/4.8, $5/$25).
    opus = cost_estimator.estimate_call("anthropic_sdk", input_chars=4000, output_chars=1000, role="opus_5")
    sonnet = cost_estimator.estimate_call("anthropic_sdk", input_chars=4000, output_chars=1000, role="sonnet_4_6")
    domyslna_rola = cost_estimator.estimate_call("anthropic_sdk", input_chars=4000, output_chars=1000)

    checks = [
        ("claude_code: koszt > 0 (bezpiecznik wolumenu)", cc > 0),
        ("ollama: koszt 0", cost_estimator.estimate_call("ollama") == 0.0),
        ("nieznane źródło: koszt 0", cost_estimator.estimate_call(None) == 0.0),
        ("sdk: koszt > 0", small > 0),
        ("sdk: więcej znaków -> większy koszt", big > small),
        ("sdk: Sonnet 4.6 jest tańszy niż Opus 5 przy tych samych znakach", sonnet < opus),
        ("sdk: brak roli -> szacunek jak dla roli domyślnej (opus_5)", domyslna_rola == opus),
        ("sdk: cena Opusa poprawiona (4000 wej. + 1000 wyj. znaków -> 0.0112 USD, nie ~0.0338 ze starych stałych)",
         abs(opus - 0.0112) < 0.0005),
    ]

    print("\n--- Wynik testu dymnego cost_estimator ---")
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
