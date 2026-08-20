"""
Osadzenie agenta w realiach firmy — wczytuje pliki z kontekst/ i dokleja właściwy
fragment do promptu.

Powód: bez tego agent wykonywał zadania poprawnie technicznie, ale obok realiów.
Nie wiedział, że Odczaruj Power BI sprzedaje wiedzę, a Clickless wdrożenia; że
ceny podaje się tylko po sprawdzeniu na stronie; że nazw klientów się nie ujawnia.
Ta wiedza nie wynika z treści zadania ani z kodu, więc musi przyjść z zewnątrz.

Dobór jest jawny i przewidywalny: `firma-podstawy.md` idzie ZAWSZE (kto jest kim,
czego nigdy nie robimy), a do tego dokładamy plik marki rozpoznanej po treści
zadania. Gdy zadanie nie wskazuje marki, agent dostaje same podstawy — nigdy nie
zgadujemy marki, bo pomyłka oznacza materiał napisany do niewłaściwego odbiorcy.

Pliki są konfiguracją, nie kodem: dopisanie akapitu działa od następnego zadania.

Użycie:
    python kontekst_firmy.py "Napisz post o kursie DAX dla Odczaruj"
"""

import sys
from pathlib import Path

import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)

KONTEKST_DIR = Path(__file__).parent / "kontekst"
PODSTAWY = "firma-podstawy.md"
MAX_ZNAKOW = 6000

# Marka rozpoznawana po treści zadania. Kolejność ma znaczenie: pierwsze trafienie
# wygrywa, więc bardziej szczegółowe wpisy (wydarzenie) stoją przed ogólnymi (marka).
#
# Słowa muszą być JEDNOZNACZNE. Samo "kurs" tu nie wystarczy: "kurs EUR" to notowanie
# waluty, a nie szkolenie — na tym mechanizm potknął się przy pierwszym teście
# i doklejał kontekst marki szkoleniowej do zadania o kursach walut.
MARKI = [
    ("wydarzenie-power-bi-day.md", ("power bi day", "powerbiday", "konferencj", "prelekcj", "prelegent")),
    ("marka-clickless.md", ("clickless", "wdrożen", "wdrozen", "audyt danych", "power apps",
                            "raportowanie dla firm", "klient wdrożeniowy")),
    ("marka-odczaruj-power-bi.md", ("odczaruj", "szkolen", "szkolen", "webinar", "uczestnik",
                                    "kurs online", "kurs power bi", "kursu", "kursy", "kursach",
                                    "społeczność", "spolecznosc", "pl-300", "kohort")),
]

# Frazy, przy których NIE dobieramy marki po słowach ogólnych — zadanie dotyczy
# danych, nie oferty. Kontekst podstawowy i tak zostaje.
WYKLUCZENIA = ("kurs eur", "kurs usd", "kurs gbp", "kurs chf", "kurs jpy", "kurs czk",
               "kurs walut", "kurs średni", "kurs sredni", "nbp", "tabela a")


def dostepne_pliki(katalog=KONTEKST_DIR):
    """Lista plików kontekstu (bez README, który jest instrukcją dla ludzi)."""
    katalog = Path(katalog)
    if not katalog.is_dir():
        return []
    return sorted(p.name for p in katalog.glob("*.md") if p.name.lower() != "readme.md")


def wybierz_pliki(tekst, katalog=KONTEKST_DIR):
    """Które pliki kontekstu pasują do zadania: zawsze podstawy + ewentualnie marka."""
    dostepne = dostepne_pliki(katalog)
    wybrane = [PODSTAWY] if PODSTAWY in dostepne else []
    nisko = (tekst or "").lower()

    # Nazwa marki wprost bije wykluczenia — "kurs EUR na stronie Clickless" nadal
    # dotyczy Clickless. Bez tego wykluczenie zjadałoby poprawne dopasowania.
    for plik, slowa in MARKI:
        if plik in dostepne and any(s in nisko for s in ("clickless", "odczaruj", "power bi day", "powerbiday")):
            if any(s in nisko for s in slowa):
                wybrane.append(plik)
                return wybrane

    if any(w in nisko for w in WYKLUCZENIA):
        return wybrane

    for plik, slowa in MARKI:
        if plik in dostepne and any(s in nisko for s in slowa):
            wybrane.append(plik)
            break
    return wybrane


def dopasuj_projekt(tekst, katalog=KONTEKST_DIR):
    """Ścieżka pliku projektu, gdy zadanie wskazuje projekt po nazwie.

    Dopasowanie idzie po nazwie z NAGŁÓWKA pliku ("# DEV - Magnapharm"), a nie po
    nazwie pliku, bo w zadaniu ludzie piszą "Magnapharm", a nie "dev-magnapharm".
    Wymagamy członu dłuższego niż 3 znaki, żeby "AXL" nie łapało przypadkowych
    skrótów, a krótkie słowa nie dopasowywały cudzych projektów."""
    katalog = Path(katalog) / "projekty"
    if not katalog.is_dir():
        return None
    nisko = (tekst or "").lower()
    najlepszy, dlugosc = None, 0
    for plik in sorted(katalog.glob("*.md")):
        if plik.name.lower() == "readme.md":
            continue
        try:
            naglowek = plik.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()
        except (OSError, IndexError):
            continue
        # Pełna nazwa też jest członem — projekt "Power BI Day Q3 2026" ludzie
        # wołają całą nazwą, nie fragmentem po myślniku.
        czlony = [naglowek.strip().lower()] + [c.strip().lower() for c in naglowek.split("-")]
        for czlon in czlony:
            if len(czlon) > 3 and czlon in nisko and len(czlon) > dlugosc:
                najlepszy, dlugosc = plik, len(czlon)
    return najlepszy


def zbuduj(tekst, katalog=KONTEKST_DIR, max_znakow=MAX_ZNAKOW):
    """Gotowy blok kontekstu do wklejenia w prompt. Pusty tekst, gdy nie ma plików —
    brak kontekstu nie może wywrócić zadania, po prostu agent pracuje bez osadzenia."""
    czesci = []
    for nazwa in wybierz_pliki(tekst, katalog):
        try:
            tresc = (Path(katalog) / nazwa).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if tresc:
            czesci.append(tresc)

    # Kontekst projektu dokładamy na końcu, bo jest najbardziej szczegółowy —
    # ustalenia z konkretnym klientem biją ogólne zasady marki.
    plik_projektu = dopasuj_projekt(tekst, katalog)
    if plik_projektu:
        try:
            tresc = plik_projektu.read_text(encoding="utf-8").strip()
            # Same nagłówki "[do uzupełnienia]" nic nie wnoszą do promptu, a zajmują
            # miejsce — dokładamy plik dopiero, gdy ktoś go faktycznie wypełnił.
            if tresc and tresc.count("[do uzupełnienia]") < 3:
                czesci.append(tresc)
        except OSError:
            pass

    if not czesci:
        return ""

    blok = "\n\n".join(czesci)
    if len(blok) > max_znakow:
        blok = blok[:max_znakow] + "\n[...kontekst przycięty do limitu...]"
    return ("--- KONTEKST FIRMY (realia, w których pracujesz; obowiązuje tak samo jak "
            "polecenie z zadania) ---\n" + blok + "\n--- KONIEC KONTEKSTU FIRMY ---")


def main():
    tekst = " ".join(sys.argv[1:]) or ""
    print("Dopasowane pliki:", ", ".join(wybierz_pliki(tekst)) or "(brak)")
    blok = zbuduj(tekst)
    print(f"Długość bloku: {len(blok)} znaków")
    print(blok[:1200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
