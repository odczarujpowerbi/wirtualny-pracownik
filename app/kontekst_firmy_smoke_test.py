"""
Test dymny kontekstu firmowego — doboru plików i wpięcia w prompty.
Bez sieci i bez modelu.

Kluczowy przypadek: "kurs EUR" to notowanie waluty, a nie szkolenie. Pierwsza
wersja doboru dokleiła do takiego zadania kontekst marki szkoleniowej — test
pilnuje, żeby to nie wróciło.

Użycie:
    python kontekst_firmy_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import bot_bozena_biznes
import kontekst_firmy
import task_brief_builder


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    checks.append(("Podstawy firmy dołączane zawsze, nawet bez rozpoznanej marki",
                   kontekst_firmy.wybierz_pliki("Podsumuj tydzień") == ["firma-podstawy.md"]))
    checks.append(("Zadanie o szkoleniach -> kontekst marki szkoleniowej",
                   "marka-odczaruj-power-bi.md" in kontekst_firmy.wybierz_pliki(
                       "Napisz opis szkolenia dla Odczaruj Power BI")))
    checks.append(("Zadanie o wdrożeniu -> kontekst marki wdrożeniowej",
                   "marka-clickless.md" in kontekst_firmy.wybierz_pliki(
                       "Przygotuj ofertę wdrożenia raportów")))
    checks.append(("Zadanie o konferencji -> kontekst wydarzenia",
                   "wydarzenie-power-bi-day.md" in kontekst_firmy.wybierz_pliki(
                       "Agenda konferencji Power BI Day")))

    # Regresja: "kurs" bez dookreślenia znaczy notowanie waluty równie dobrze jak szkolenie.
    walutowe = kontekst_firmy.wybierz_pliki("Sprawdź kurs EUR wg NBP")
    checks.append(("Kurs waluty NIE dobiera kontekstu marki szkoleniowej",
                   walutowe == ["firma-podstawy.md"]))
    checks.append(("Nazwa marki wprost bije wykluczenie walutowe",
                   "marka-clickless.md" in kontekst_firmy.wybierz_pliki(
                       "Kurs EUR do rozliczenia w Clickless")))

    blok = kontekst_firmy.zbuduj("Opis kursu dla Odczaruj")
    checks.append(("Blok kontekstu jest oznaczony znacznikami", "KONTEKST FIRMY" in blok
                   and "KONIEC KONTEKSTU FIRMY" in blok))
    checks.append(("Blok niesie zasady, których agent ma pilnować",
                   "Nie podaje ceny ani terminu z pamięci" in blok))

    dlugi = kontekst_firmy.zbuduj("Opis kursu dla Odczaruj", max_znakow=200)
    checks.append(("Zbyt długi kontekst jest przycinany, nie rozdyma promptu", len(dlugi) < 400))

    with tempfile.TemporaryDirectory() as tmp:
        checks.append(("Brak katalogu kontekstu -> pusty blok, bez wyjątku",
                       kontekst_firmy.zbuduj("cokolwiek", katalog=Path(tmp) / "nie_ma") == ""))

    prompt = task_brief_builder.build_thinking_prompt(
        {"title": "Napisz opis kursu dla Odczaruj Power BI", "description": ""})
    checks.append(("Kontekst trafia do analizy zadania", "KONTEKST FIRMY" in prompt))

    ocena = bot_bozena_biznes.build_prompt(
        {"title": "Oferta wdrożenia dla Clickless"}, {"acceptance_notes": "x"},
        {"oczekiwania": "", "na_co_uwaga": []}, "", {})
    checks.append(("Kontekst trafia do odbioru biznesowego", "KONTEKST FIRMY" in ocena))
    checks.append(("Odbiór dostaje właściwą markę", "Clickless — marka wdrożeniowa" in ocena))

    print("\n--- Wynik testu dymnego kontekstu firmowego ---")
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
