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

    checks = [
        ("claude_code: koszt > 0 (bezpiecznik wolumenu)", cc > 0),
        ("ollama: koszt 0", cost_estimator.estimate_call("ollama") == 0.0),
        ("nieznane źródło: koszt 0", cost_estimator.estimate_call(None) == 0.0),
        ("sdk: koszt > 0", small > 0),
        ("sdk: więcej znaków -> większy koszt", big > small),
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
