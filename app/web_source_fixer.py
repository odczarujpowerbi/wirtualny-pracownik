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
