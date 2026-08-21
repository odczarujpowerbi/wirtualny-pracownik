"""
Zamiana WZGLĘDNEGO okresu z treści zadania ("za ostatni tydzień", "wczoraj",
"w tym miesiącu") na KONKRETNE daty. Czysty Python, zero AI — bo to jest
dokładnie ten rodzaj rzeczy, w którym model potrafi się pomylić o jeden dzień,
a odbiorca dostaje wtedy raport za zły okres i nie ma jak tego zauważyć.

Dwie zasady, obie wynikają z odbioru biznesowego:
  1. Okres jest ZAWSZE zwracany razem z opisem po polsku — materiał dla
     człowieka musi mówić wprost "za okres 13-19.08.2026", a nie "za ostatni
     tydzień" (bo "ostatni tydzień" czytane tydzień później znaczy co innego).
  2. Gdy w zadaniu nie ma żadnej wskazówki o okresie, NIE zgadujemy — zwracamy
     None, a worker prosi człowieka o doprecyzowanie. Domyślne "ostatnie 7 dni"
     wyglądałoby na wykonane zadanie, a byłoby zgadywaniem.

Konwencja "ostatni tydzień": ostatnie 7 pełnych dni licząc wstecz od WCZORAJ
włącznie (dziś jest niepełne — kampania wysłana dziś rano ma jeszcze zbierać
otwarcia). Dla "poprzedni tydzień" bierzemy kalendarzowy pon-niedz.
"""

import re
from datetime import date, timedelta

MIESIACE_PL = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
               "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]


def _fmt(d):
    return f"{d.day}.{d.month:02d}.{d.year}"


def _opis(od, do):
    """Czytelny opis zakresu dla człowieka: '13-19 sierpnia 2026' albo pełne daty
    gdy zakres przechodzi przez granicę miesiąca."""
    if od.year == do.year and od.month == do.month:
        return f"{od.day}-{do.day} {MIESIACE_PL[od.month - 1]} {od.year}"
    return f"{_fmt(od)} - {_fmt(do)}"


def resolve(tekst, dzis=None):
    """Zwraca {'od': date, 'do': date, 'opis': str, 'fraza': str} albo None,
    gdy w tekście nie ma żadnej wskazówki o okresie.

    'od' i 'do' są WŁĄCZNE (oba dni należą do okresu)."""
    dzis = dzis or date.today()
    t = (tekst or "").lower()
    wczoraj = dzis - timedelta(days=1)

    # Kolejność ma znaczenie: "poprzedni tydzień" musi wygrać z "tydzień".
    if re.search(r"poprzedni(m|ego)?\s+tygodni", t) or "zeszły tydzień" in t or "zeszłym tygodniu" in t:
        poniedzialek_tego = dzis - timedelta(days=dzis.weekday())
        od = poniedzialek_tego - timedelta(days=7)
        return {"od": od, "do": od + timedelta(days=6), "opis": _opis(od, od + timedelta(days=6)),
                "fraza": "poprzedni tydzień kalendarzowy (pon-niedz)"}

    if re.search(r"ostatni\w*\s+(\d+)\s+dni", t):
        n = int(re.search(r"ostatni\w*\s+(\d+)\s+dni", t).group(1))
        od = wczoraj - timedelta(days=n - 1)
        return {"od": od, "do": wczoraj, "opis": _opis(od, wczoraj), "fraza": f"ostatnie {n} dni"}

    if re.search(r"ostatni\w*\s+tygodni|ostatni tydzie|w tym tygodniu|tygodniow", t):
        od = wczoraj - timedelta(days=6)
        return {"od": od, "do": wczoraj, "opis": _opis(od, wczoraj), "fraza": "ostatnie 7 dni"}

    if "wczoraj" in t:
        return {"od": wczoraj, "do": wczoraj, "opis": _fmt(wczoraj), "fraza": "wczoraj"}

    if re.search(r"ostatni\w*\s+miesi|w tym miesi|miesi[ęe]czn", t):
        pierwszy = dzis.replace(day=1)
        od = (pierwszy - timedelta(days=1)).replace(day=1)
        do = pierwszy - timedelta(days=1)
        return {"od": od, "do": do, "opis": _opis(od, do), "fraza": "poprzedni miesiąc kalendarzowy"}

    return None


if __name__ == "__main__":
    dzis = date(2026, 8, 20)
    for fraza in ["zestawienie za ostatni tydzień", "podsumowanie z poprzedniego tygodnia",
                  "za ostatnie 14 dni", "co było wczoraj", "raport miesięczny", "zrób zestawienie"]:
        print(f"{fraza:42} -> {resolve(fraza, dzis)}")
