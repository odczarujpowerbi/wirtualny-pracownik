"""
Samodzielna korekta adresu źródła, gdy wskazany link nie zawiera odpowiedzi na
zadanie. Powód wprost z odbioru biznesowego: zadanie "podaj kurs jena" ze
wskazanym adresem kursu euro zostało odesłane do człowieka z prośbą o źródło,
a odbiór słusznie zauważył, że kurs jena jest w tej samej, publicznej tabeli NBP
i agent powinien go po prostu wziąć, zamiast przerzucać pracę z powrotem.

Zakres jest wąski i deterministyczny: TYLKO źródła, dla których skill
(skills/web_research_operations.yaml) definiuje regułę `korekta_adresu`, i tylko
przez podstawienie dopasowanego fragmentu treści zadania do szablonu adresu.
Żadnego zgadywania adresów — czego nie ma w regule, tego nie poprawiamy.

Wynik i tak przechodzi przez kontrakt narzędzia (allowlista hostów), więc reguła
nie jest w stanie wyprowadzić agenta poza dozwolone źródła.

Użycie:
    python web_source_fixer.py "Podaj kurs JPY" https://api.nbp.pl/api/exchangerates/rates/a/eur/
"""

import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import yaml

import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)

SKILL_PATH = Path(__file__).parent / "skills" / "web_research_operations.yaml"


def _reguly(path=SKILL_PATH):
    try:
        dane = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {host: (wpis or {}).get("korekta_adresu")
            for host, wpis in (dane.get("zrodla") or {}).items() if (wpis or {}).get("korekta_adresu")}


def fallback_po_bledzie(url, kod, path=SKILL_PATH):
    """Adres zastępczy, gdy źródło odpowiedziało błędem, a skill wie, co wtedy
    zrobić — np. NBP nie publikuje tabeli w dni wolne, więc bierzemy ostatnie
    opublikowane notowanie. Zwraca (adres, adnotacja) albo (None, None).

    Adnotacja jest istotna: dane pochodzą wtedy z innego dnia niż zamówiony
    i odpowiedź MUSI to powiedzieć wprost, inaczej jest myląca."""
    host = (urlparse(url or "").hostname or "").lower()
    regula = (_wpis(host, path).get("fallback_przy_bledzie") or {}).get(kod)
    if not regula:
        return None, None

    wzorzec = regula.get("wzorzec")
    if not wzorzec:
        return None, None

    if regula.get("tryb") == "zakres_dni_wstecz":
        nowy = _zakres_przed_data(url, wzorzec, int(regula.get("dni", 10)))
        return (nowy, regula.get("adnotacja")) if nowy else (None, None)

    zamiana = regula.get("zamiana")
    if not zamiana:
        return None, None
    nowy, ile = re.subn(wzorzec, zamiana, url)
    if not ile or nowy == url:
        return None, None
    return nowy, regula.get("adnotacja")


def _zakres_przed_data(url, wzorzec, dni):
    """Zamienia adres pojedynczego dnia na zakres kończący się TYM dniem.

    Kluczowe dla poprawności: pytanie o dzień wolny musi dać notowanie
    poprzedzające tę datę, a nie notowanie najnowsze. Endpoint "last/1" zwróciłby
    kurs z dzisiaj i odpowiedź byłaby merytorycznie fałszywa."""
    trafienie = re.search(wzorzec, url or "")
    if not trafienie or trafienie.lastindex is None or trafienie.lastindex < 2:
        return None
    waluta, data = trafienie.group(1), trafienie.group(2)
    try:
        koniec = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        return None
    poczatek = koniec - timedelta(days=dni)
    return url.replace(f"/rates/a/{waluta}/{data}/",
                       f"/rates/a/{waluta}/{poczatek.isoformat()}/{data}/")


def _wpis(host, path=SKILL_PATH):
    try:
        dane = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return (dane.get("zrodla") or {}).get(host) or {}


def popraw_adres(url, tekst_zadania, path=SKILL_PATH):
    """Zwraca poprawiony adres albo None, gdy nie ma reguły dla tego hosta,
    treść zadania nic nie wskazuje, albo wynik byłby taki sam jak oryginał."""
    host = (urlparse(url or "").hostname or "").lower()
    regula = _reguly(path).get(host)
    if not regula:
        return None

    wzorzec = regula.get("wzorzec_zadania")
    szablon = regula.get("szablon")
    if not wzorzec or not szablon:
        return None

    trafienie = re.search(wzorzec, tekst_zadania or "", re.IGNORECASE)
    if not trafienie:
        return None

    nowy = szablon.format(dopasowanie=trafienie.group(1).lower())
    return nowy if nowy != url else None


def main():
    if len(sys.argv) < 3:
        print("Użycie: python web_source_fixer.py <treść zadania> <adres>")
        return 1
    print(popraw_adres(sys.argv[2], sys.argv[1]) or "(brak korekty)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
