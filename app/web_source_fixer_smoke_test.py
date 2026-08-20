"""
Test dymny web_source_fixer — samodzielnej korekty adresu źródła. Bez sieci
i bez modelu: sprawdzamy samą regułę i jej granice.

Pokrywa też odmowę executora dla adresu spoza allowlisty — zachowanie, którego
brak powodował realny błąd: zadanie ze źródłem spoza listy kończyło się statusem
"done" bez wykonanej pracy.

Użycie:
    python web_source_fixer_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import executor
import web_source_fixer

NBP_EUR = "https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    poprawiony = web_source_fixer.popraw_adres(NBP_EUR, "Podaj kurs jena JPY wg NBP")
    checks.append(("Adres innej waluty jest poprawiany wg treści zadania",
                   poprawiony == "https://api.nbp.pl/api/exchangerates/rates/a/jpy/?format=json"))
    checks.append(("Poprawiony adres zostaje na dozwolonym hoście",
                   poprawiony.startswith("https://api.nbp.pl/")))

    checks.append(("Brak waluty w zadaniu -> brak korekty (nie zgadujemy)",
                   web_source_fixer.popraw_adres(NBP_EUR, "Przygotuj raport miesięczny") is None))
    checks.append(("Ten sam adres co oryginał -> None, żeby nie pobierać dwa razy",
                   web_source_fixer.popraw_adres(NBP_EUR, "kurs EUR") is None))
    checks.append(("Źródło bez reguły korekty -> None",
                   web_source_fixer.popraw_adres("https://pl.wikipedia.org/x", "kurs JPY") is None))
    checks.append(("Słowo zawierające kod waluty nie wyzwala korekty (granice słowa)",
                   web_source_fixer.popraw_adres(NBP_EUR, "raport EUROPEJSKI za sierpień") is None))

    with tempfile.TemporaryDirectory() as tmp:
        brak = Path(tmp) / "nie_ma.yaml"
        checks.append(("Brak pliku skilla -> None, bez wyjątku",
                       web_source_fixer.popraw_adres(NBP_EUR, "kurs JPY", path=brak) is None))

    # --- odmowa dla źródła spoza allowlisty (regresja: kończyło się cichym "done") ---
    odmowa = executor.execute({"title": "Zbierz cennik",
                               "description": "Sprawdź ceny: https://przypadkowa-strona.example/cennik"})
    checks.append(("Źródło spoza allowlisty -> odmowa, nie ciche 'brak workera'",
                   odmowa is not None and odmowa["executed"] is False))
    checks.append(("Odmowa mówi, czego brakuje i czyja to decyzja",
                   "allowed_domains" in odmowa["acceptance_notes"]
                   and "właściciel" in odmowa["acceptance_notes"].lower()))
    checks.append(("Zadanie bez adresu nadal idzie dotychczasową ścieżką (None)",
                   executor.execute({"title": "Przygotuj podsumowanie tygodnia"}) is None))

    print("\n--- Wynik testu dymnego web_source_fixer ---")
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
