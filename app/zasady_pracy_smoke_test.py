"""
Test dymny zasady_pracy.py. Zero sieci, zero modelu: czyta tylko pliki regul z
.claude/rules i sprawdza dobor.

Uzycie:
    python zasady_pracy_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import zasady_pracy


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. Zadanie czysto tekstowe nie dostaje zadnych standardow (regresja: slowo
    # "napisz" zawiera podciag "api", co doklejalo caly plik standardow kodu).
    zakres_tekstowy = zasady_pracy.wykryj_zakres({"title": "Napisz posta na LinkedIn o webinarze"})
    checks.append(("Zadanie tekstowe: brak regul (napisz != api)", zakres_tekstowy == []))

    # 2. Zadanie o kodzie dostaje standardy kodu.
    zakres_kod = zasady_pracy.wykryj_zakres({"title": "Popraw kod walidacji w aplikacji"})
    checks.append(("Zadanie o kodzie: coding-rules.md", zasady_pracy.CODE_RULES in zakres_kod))
    checks.append(("Zadanie o kodzie bez repo: BRAK git-workflow.md",
                   zasady_pracy.GIT_RULES not in zakres_kod))

    # 3. Praca w repozytorium zawsze dokłada konwencje commitow.
    zakres_repo = zasady_pracy.wykryj_zakres({"title": "Zrob cokolwiek"}, praca_w_repo=True)
    checks.append(("Praca w repo: git-workflow.md + coding-rules.md",
                   zakres_repo == [zasady_pracy.GIT_RULES, zasady_pracy.CODE_RULES]))

    # 4. Power BI rozpoznawane po tresci, niezaleznie od repo.
    zakres_pbi = zasady_pracy.wykryj_zakres({"title": "Popraw miary DAX w raporcie Power BI"})
    checks.append(("Zadanie Power BI: power-bi-standards.md",
                   zasady_pracy.POWER_BI_RULES in zakres_pbi))

    # 5. Blok tresci: realna konwencja commitow z pliku regul, nie parafraza.
    blok_repo = zasady_pracy.blok({"title": "Popraw kod"}, praca_w_repo=True)
    checks.append(("Blok repo niesie konwencje commitow z pliku regul",
                   "numer dwucyfrowy" in blok_repo))
    checks.append(("Blok repo mowi, ze standardy sa obowiazujace",
                   "STANDARDY OBOWIAZUJACE" in blok_repo))
    checks.append(("Blok repo nie przekracza limitu znakow",
                   len(blok_repo) <= zasady_pracy.MAX_ZNAKOW))

    # 6. Zadanie bez potrzeby standardow -> pusty blok (zero zmarnowanych tokenow).
    checks.append(("Zadanie tekstowe: blok pusty",
                   zasady_pracy.blok({"title": "Napisz posta na LinkedIn"}) == ""))

    # 7. Fail-soft: brak katalogu regul nie wywala promptu.
    pusty_katalog = Path(tempfile.mkdtemp()) / "brak-regul"
    blok_bez_regul = zasady_pracy.blok({"title": "Popraw kod"}, praca_w_repo=True,
                                       rules_dir=pusty_katalog)
    checks.append(("Brak katalogu regul: fail-soft, pusty blok", blok_bez_regul == ""))

    print("\n--- Wynik testu dymnego zasady_pracy ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedl.")
        sys.exit(1)
    print("\nWszystkie testy przeszly.")


if __name__ == "__main__":
    run()
