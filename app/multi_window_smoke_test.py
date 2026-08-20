"""
Test dymny multi_window. Sprawdza matematyke siatki (plan_grid/choose_grid) i
lagodna degradacje arrange/capture_all bez realnych okien. Uzywa malo
prawdopodobnych tytulow, wiec wynik jest deterministyczny.

Uzycie: python multi_window_smoke_test.py
"""

import sys
import tempfile

import multi_window as mw

_FAKE = ["zzz_okno_a_9f3", "zzz_okno_b_9f3", "zzz_okno_c_9f3"]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = [
        ("choose_grid: 16 -> 4x4", mw.choose_grid(16) == (4, 4)),
        ("choose_grid: 12 -> 4x3", mw.choose_grid(12) == (4, 3)),
        ("choose_grid: 0 -> 0x0", mw.choose_grid(0) == (0, 0)),
    ]

    cells = mw.plan_grid(16, 7680, 4320, padding=0)
    checks.append(("plan_grid: 16 komorek", len(cells) == 16))
    checks.append(("plan_grid: pierwsza komorka 1920x1080 @ (0,0)", cells[0] == (0, 0, 1920, 1080)))
    checks.append(("plan_grid: druga kolumna @ x=1920", cells[1][0] == 1920))
    checks.append(("plan_grid: drugi wiersz @ y=1080", cells[4][1] == 1080))

    padded = mw.plan_grid(4, 1000, 1000, padding=10)
    checks.append(("plan_grid: padding zmniejsza komorke", padded[0][2] == 480 and padded[0][3] == 480))
    checks.append(("plan_grid: count<=0 -> []", mw.plan_grid(0, 100, 100) == []))

    arranged = mw.arrange(_FAKE, screen_w=1920, screen_h=1080)
    checks.append(("arrange: zwraca wpis na okno", len(arranged) == 3))
    checks.append(("arrange: brak okien -> ok False (bez crasha)", all(a["ok"] is False for a in arranged)))

    with tempfile.TemporaryDirectory() as tmp:
        shots = mw.capture_all(_FAKE, out_dir=tmp)
    checks.append(("capture_all: dict na kazde okno", set(shots.keys()) == set(_FAKE)))
    checks.append(("capture_all: brak okien -> available False (bez crasha)",
                   all(v["available"] is False for v in shots.values())))

    print("\n--- Wynik testu dymnego multi_window ---")
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
