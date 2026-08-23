"""
Generator szkiców kontekstu projektów — z danych, które już są w Projectly.

Po co: kontekst projektu (kto jest po drugiej stronie, jakie systemy, na jakim
etapie jesteśmy) trzeba spisać raz, ale przepisywanie ręcznie nazw i tematów
15 projektów to strata czasu. Skrypt wypełnia to, co da się wyczytać z zadań,
i zostawia jawne miejsca `[do uzupełnienia]` tam, gdzie potrzebna jest wiedza
właściciela — bo zgadywanie ustaleń z klientem byłoby gorsze niż ich brak.

Bezpieczeństwo pracy: bez `--yes` skrypt tylko pokazuje, co by zrobił, i NIGDY
nie nadpisuje pliku, który ktoś już uzupełnił.

Użycie:
    python kontekst_projektow_seed.py            # podgląd
    python kontekst_projektow_seed.py --yes      # zapis szkiców
    python kontekst_projektow_seed.py --yes --projekt "DEV - Anava"
"""

import argparse
import re
import sys
from pathlib import Path

import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)
from projectly_client import ProjectlyClient, get_client

PROJEKTY_DIR = Path(__file__).parent / "kontekst" / "projekty"
MAX_TEMATOW = 8

# Projekty, których nie opisujemy: prywatne sprawy właściciela nie są kontekstem
# firmowym i nie mają czego szukać w prompcie agenta.
POMIJANE = ("prywatne",)

# Z nazwy projektu wynika marka i charakter pracy — to jedyne, co wolno wywnioskować
# automatycznie, bo wynika z konwencji nazewnictwa, a nie z domysłu.
def _marka_i_typ(nazwa):
    n = nazwa.lower()
    if n.startswith("dev - "):
        return "Clickless", "wdrożenie u klienta"
    if "clickless" in n:
        return "Clickless", "sprzedaż i marketing marki wdrożeniowej"
    if "odczaruj" in n:
        return "Odczaruj Power BI", "sprzedaż i marketing marki szkoleniowej"
    if "power bi day" in n:
        return "Odczaruj Power BI", "organizacja konferencji"
    if "szkolenia" in n:
        return "Odczaruj Power BI", "realizacja szkoleń"
    return "[do uzupełnienia]", "[do uzupełnienia]"


# Polskie znaki trzeba zamienić, a nie wyciąć: bez tego "Sprzedaż Clickless"
# dawało plik "sprzeda-clickless" i nazwa przestawała być rozpoznawalna.
_TRANSLITERACJA = str.maketrans({"ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n",
                                 "ó": "o", "ś": "s", "ż": "z", "ź": "z"})


def nazwa_pliku(nazwa_projektu):
    """Nazwa projektu -> nazwa pliku, po której kontekst_firmy dobiera plik."""
    tekst = nazwa_projektu.lower().translate(_TRANSLITERACJA).replace(" - ", "-")
    slug = re.sub(r"[^a-z0-9]+", "-", tekst).strip("-")
    return f"{slug}.md"


def zbuduj_szkic(nazwa, zadania):
    marka, typ = _marka_i_typ(nazwa)
    tematy = [(t.get("title") or "").strip() for t in zadania][:MAX_TEMATOW]
    lista_tematow = "\n".join(f"- {t}" for t in tematy if t) or "- (brak zadań w Projectly)"
    return f"""# {nazwa}

Szkic wygenerowany z Projectly. Sekcje `[do uzupełnienia]` wypełnia właściciel —
to wiedza, której nie ma w żadnym systemie.

- **Marka:** {marka}
- **Typ pracy:** {typ}
- **Zadań w Projectly:** {len(zadania)}

## Z czego składa się ten projekt

Przykładowe zadania (najświeższe w Projectly):

{lista_tematow}

## Kto jest po drugiej stronie

[do uzupełnienia] — osoba kontaktowa, jej rola, czego oczekuje, jak lubi
dostawać informacje (mail, telefon, raport).

## Systemy i dane

[do uzupełnienia] — z czego ciągniemy dane, gdzie leżą raporty, jakie są dostępy.

## Etap i ustalenia

[do uzupełnienia] — na czym stanęło, co obiecaliśmy, jakie terminy obowiązują.

## Na co uważać

[do uzupełnienia] — wrażliwe tematy, rzeczy ustalone inaczej niż standardowo,
czego przy tym kliencie nie robimy.
"""


def zbierz(client=None, tylko_projekt=None):
    """Zwraca listę (nazwa_projektu, zadania) dla aktywnych projektów."""
    client = client or get_client()
    if not isinstance(client, ProjectlyClient):
        raise SystemExit("Brak PROJECTLY_API_KEY w secrets/.env — nie ma z czego generować.")
    client._ensure_directory()

    wynik = []
    for projekt in client._projects:
        nazwa = projekt.get("name", "")
        if projekt.get("status") != "active":
            continue
        if any(p in nazwa.lower() for p in POMIJANE):
            continue
        if tylko_projekt and nazwa.lower() != tylko_projekt.lower():
            continue
        odpowiedz = client._mcp.call_tool("get_project_tasks", {"projectId": projekt["id"]})
        zadania = odpowiedz.get("tasks", []) if isinstance(odpowiedz, dict) else []
        wynik.append((nazwa, zadania))
    return wynik


def zapisz(projekty, katalog=PROJEKTY_DIR, wykonaj=False):
    """Zapisuje szkice. Zwraca listę (nazwa_pliku, status)."""
    katalog = Path(katalog)
    raport = []
    for nazwa, zadania in projekty:
        plik = katalog / nazwa_pliku(nazwa)
        if plik.exists():
            # Plik uzupełniony ręcznie jest cenniejszy niż świeży szkic — nigdy
            # go nie nadpisujemy, nawet przy ponownym uruchomieniu generatora.
            raport.append((plik.name, "pominięty (już istnieje)"))
            continue
        if not wykonaj:
            raport.append((plik.name, f"do utworzenia ({len(zadania)} zadań)"))
            continue
        katalog.mkdir(parents=True, exist_ok=True)
        plik.write_text(zbuduj_szkic(nazwa, zadania), encoding="utf-8")
        raport.append((plik.name, "utworzony"))
    return raport


def main():
    parser = argparse.ArgumentParser(description="Generuje szkice kontekstu projektów z Projectly.")
    parser.add_argument("--yes", action="store_true", help="Zapisz pliki (bez tego: podgląd)")
    parser.add_argument("--projekt", help="Tylko ten jeden projekt")
    args = parser.parse_args()

    projekty = zbierz(tylko_projekt=args.projekt)
    for nazwa, status in zapisz(projekty, wykonaj=args.yes):
        print(f"{status:28} {nazwa}")
    if not args.yes:
        print("\nTo był podgląd. Uruchom z --yes, żeby zapisać.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
