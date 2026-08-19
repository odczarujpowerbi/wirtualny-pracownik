"""
Test dymny pbi_desktop_bridge. NIGDY nie otwiera realnie Power BI: podmienia
_launch na atrapę i wstrzykuje `sleep`, żeby cykliczny self_check był bezpieczny
i szybki (żadnego GUI, żadnego czekania). Sprawdza wyłącznie łagodną degradację
i walidację ścieżki — sama warstwa GUI wymaga prawdziwego Windows z Power BI.

Użycie:
    python pbi_desktop_bridge_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import pbi_desktop_bridge


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    missing = pbi_desktop_bridge.open_and_capture("nie_ma_takiej_sciezki_pbip_123")
    checks.append(("open_and_capture: brak ścieżki -> available False",
                   missing["available"] is False and "nie istnieje" in missing["detail"]))

    original_launch = pbi_desktop_bridge._launch
    try:
        pbi_desktop_bridge._launch = lambda p: (True, "atrapa uruchomienia (bez realnego GUI)")
        with tempfile.TemporaryDirectory() as tmp:
            res = pbi_desktop_bridge.open_and_capture(
                tmp, wait_seconds=6, title_hint="zzz_okno_nieistniejace_9f3a1c", sleep=lambda s: None)
        # Bez backendu okien albo bez znalezionego okna -> available False, nie crash.
        checks.append(("open_and_capture: brak okna/backendu -> available False (nie rzuca)",
                       res["available"] is False and bool(res["detail"])))
    finally:
        pbi_desktop_bridge._launch = original_launch

    found = pbi_desktop_bridge._wait_for_window("zzz_okno_nieistniejace_9f3a1c", 4, sleep=lambda s: None)
    checks.append(("_wait_for_window: brak okna -> False (bez realnego czekania)", found is False))

    print("\n--- Wynik testu dymnego pbi_desktop_bridge ---")
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
