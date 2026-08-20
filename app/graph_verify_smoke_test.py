"""
Test dymny graph_verify. Sprawdza logike bez sieci (brak zmiennych -> stage env).
Nie dotyka Graph ani sekretow - czysci MS_GRAPH_* na czas testu i przywraca.

Uzycie: python graph_verify_smoke_test.py
"""

import os
import sys

import graph_verify


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    saved = {k: os.environ.pop(k, None) for k in graph_verify._REQUIRED}
    try:
        checks.append(("missing_env: brak wszystkich -> lista 4 kluczy",
                       len(graph_verify.missing_env()) == 4))

        res = graph_verify.verify()
        checks.append(("verify: brak env -> ok False, stage env",
                       res["ok"] is False and res["stage"] == "env"))

        # Wszystkie ustawione (atrapy) -> missing_env puste (happy path logiki env).
        for k in graph_verify._REQUIRED:
            os.environ[k] = "x"
        checks.append(("missing_env: wszystkie ustawione -> []",
                       graph_verify.missing_env() == []))
    finally:
        for k in graph_verify._REQUIRED:
            os.environ.pop(k, None)
            if saved.get(k) is not None:
                os.environ[k] = saved[k]

    print("\n--- Wynik testu dymnego graph_verify ---")
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
