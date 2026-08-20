"""
Test dymny ui_actions. Sprawdza kontrakt (available + degradacja): akcje na
nieistniejacym oknie zwracaja {ok: False} i nie rzucaja. Bez realnego GUI.

Uzycie: python ui_actions_smoke_test.py
"""

import sys

import ui_actions

_UNLIKELY = "zzz_okno_nieistniejace_9f3a1c"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    avail = ui_actions.available()
    checks = [
        ("available: zwraca {available, detail}", set(avail.keys()) == {"available", "detail"}),
    ]

    c = ui_actions.click(_UNLIKELY, "Przycisk")
    checks.append(("click: brak okna -> ok False + detail", c["ok"] is False and bool(c["detail"])))

    t = ui_actions.set_text(_UNLIKELY, "Pole", "x")
    checks.append(("set_text: brak okna -> ok False", t["ok"] is False))

    lst = ui_actions.list_controls(_UNLIKELY)
    checks.append(("list_controls: brak okna -> ok False, controls []",
                   lst["ok"] is False and lst["controls"] == []))

    print("\n--- Wynik testu dymnego ui_actions ---")
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
