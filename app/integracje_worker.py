"""
Workery dla zadań opartych o konektory firmowe: MailerLite (zestawienie wysyłek)
i Zanfia (podsumowanie sprzedaży kursów). Wołane z executor.py tą samą ścieżką
co walidacja PBIP i pobranie strony — ten sam kontrakt wyniku, ta sama bramka
kontraktów narzędzi przed wywołaniem czegokolwiek.

Dlaczego osobny plik, a nie kolejne 200 linii w executor.py: executor jest już
rozdzielaczem dla pięciu rodzajów zadań i rośnie przy każdej integracji. Tutaj
mieszka wiedza "jak zbudować TEN raport", tam zostaje samo "które zadanie do
kogo".

Zasada wspólna dla obu workerów i najważniejsza rzecz w tym pliku: żaden z nich
nie ma prawa oddać materiału, którego nie da się obronić danymi. Brak klucza,
odmowa serwera, nierozpoznany okres, dane z mocka — każde z tych zdarzeń kończy
się odmową z powodem po polsku (człowiek dostaje ją w Projectly i wie, co
zrobić), nigdy raportem z liczbami wziętymi skądinąd.
"""

import json
from datetime import datetime
from pathlib import Path

import period_resolver
import tool_registry
import web_answer
from mailerlite_client import MailerLiteNiedostepny, get_mailerlite_client
from zanfia_client import ZanfiaNiedostepna, get_zanfia_client

KATALOG_WYNIKOW = Path(__file__).parent / "runs" / "integracje"


def _tekst_zadania(task):
    return " ".join(str(task.get(p) or "") for p in
                    ("title", "description", "expected_result", "acceptance_criteria"))


def czy_mailerlite(task):
    tekst = _tekst_zadania(task).lower()
    return "mailerlite" in tekst or "mailer lite" in tekst


def czy_zanfia(task):
    tekst = _tekst_zadania(task).lower()
    return "zanfia" in tekst or "zanfie" in tekst


def _odmowa(powod, tool):
    return {"cost_usd": 0.0, "tool": tool, "executed": False,
            "acceptance_notes": powod, "output": {"refused": powod}}


def _nie_wykonano(powod, tool, sygnatura=None):
    """Wykonaliśmy próbę, ale nie ma z czego zbudować materiału. Inaczej niż
    odmowa: to nie jest zdarzenie bezpieczeństwa, tylko brak danych."""
    return {"cost_usd": 0.0, "tool": tool, "executed": True,
            "acceptance_notes": "NIE WYKONANO — " + powod,
            "output": sygnatura or {}}


def _zapisz_surowe(nazwa, dane):
    """Surowa odpowiedź źródła na dysk — dowód, na czym oparty jest raport
    (kontrola funkcjonalna Franka wskazuje właśnie ten plik). runs/ jest
    w .gitignore, więc nic z tego nie trafia do repozytorium."""
    KATALOG_WYNIKOW.mkdir(parents=True, exist_ok=True)
    stempel = datetime.now().strftime("%Y%m%d-%H%M%S")
    sciezka = KATALOG_WYNIKOW / (nazwa + "-" + stempel + ".json")
    sciezka.write_text(json.dumps(dane, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(sciezka)


def _okres(task, tool):
    """Okres z treści zadania albo odmowa. Nie ma domyślnego 'ostatnie 7 dni' —
    zgadnięty okres dałby raport, który wygląda poprawnie i jest o czymś innym,
    niż zamówił człowiek."""
    okres = period_resolver.resolve(_tekst_zadania(task))
    if not okres:
        return None, _odmowa(
            "W zadaniu nie ma napisane, za jaki okres ma być zestawienie, a nie zgaduję okresu — "
            "raport za zły tydzień wygląda tak samo wiarygodnie jak za właściwy. "
            "Dopisz w zadaniu okres (np. 'za ostatni tydzień', 'za poprzedni tydzień', 'za ostatnie 30 dni').",
            tool)
    return okres, None


# --------------------------------------------------------------------------
# MailerLite — zestawienie wysyłek
# --------------------------------------------------------------------------

def _liczba(wartosc):
    """Liczba do tabeli albo '—' (brak pomiaru). Świadomie NIE 0: zero to
    wynik pomiaru, myślnik to informacja, że tego pola nie dostaliśmy."""
    return "—" if wartosc is None else str(wartosc)


def _procent(wartosc):
    return "—" if wartosc is None else ("%.1f%%" % wartosc).replace(".", ",")


def _tabela_kampanii(kampanie):
    naglowek = ("| Data | Temat | Odbiorcy | Otwarcia | Open rate | Kliknięcia | CTR | Rezygnacje |\n"
                "|---|---|---|---|---|---|---|---|")
    wiersze = []
    for k in kampanie:
        wiersze.append("| %s | %s | %s | %s | %s | %s | %s | %s |" % (
            k["data_wysylki"].strftime("%d.%m"),
            (k["temat"] or "(bez tematu)").replace("|", "/"),
            _liczba(k["odbiorcy"]), _liczba(k["otwarcia"]), _procent(k["open_rate"]),
            _liczba(k["klikniecia"]), _procent(k["ctr"]), _liczba(k["rezygnacje"])))
    return "\n".join([naglowek] + wiersze)


def _odmiana(liczba, pojedyncza, mnoga_2_4, mnoga_5):
    """Polska odmiana rzeczownika po liczbie: 1 wysyłka, 2 wysyłki, 5 wysyłek.
    'Łącznie: 2 wysyłek' czyta się jak błąd maszyny i podważa zaufanie do
    całego zestawienia — a to jest materiał, który człowiek przekleja dalej."""
    liczba = abs(liczba)
    if liczba == 1:
        return pojedyncza
    reszta_10, reszta_100 = liczba % 10, liczba % 100
    if 2 <= reszta_10 <= 4 and not 12 <= reszta_100 <= 14:
        return mnoga_2_4
    return mnoga_5


def _podsumowanie_liczbowe(kampanie):
    """Suma tylko z tych kampanii, dla których mamy komplet danych — sumowanie
    po pominięciu braków dawałoby zaniżony wynik podany jako pewny."""
    z_danymi = [k for k in kampanie if k["odbiorcy"] is not None]
    if not z_danymi:
        return "Łącznych liczb nie podaję — MailerLite nie zwrócił liczby odbiorców dla żadnej z kampanii."
    odbiorcy = sum(k["odbiorcy"] for k in z_danymi)
    otwarcia = sum(k["otwarcia"] for k in z_danymi if k["otwarcia"] is not None)
    klikniecia = sum(k["klikniecia"] for k in z_danymi if k["klikniecia"] is not None)
    linia = "Łącznie: %d %s, %d odbiorców, %d otwarć (%s), %d kliknięć (%s)." % (
        len(z_danymi), _odmiana(len(z_danymi), "wysyłka", "wysyłki", "wysyłek"), odbiorcy, otwarcia,
        _procent(round(100.0 * otwarcia / odbiorcy, 2) if odbiorcy else None),
        klikniecia, _procent(round(100.0 * klikniecia / odbiorcy, 2) if odbiorcy else None))
    bez_danych = len(kampanie) - len(z_danymi)
    if bez_danych:
        linia += (" (Pominięto w sumach %d %s bez pełnych statystyk — %s w tabeli powyżej.)"
                  % (bez_danych, _odmiana(bez_danych, "kampanię", "kampanie", "kampanii"),
                     _odmiana(bez_danych, "widać ją", "widać je", "widać je")))
    return linia


def raport_mailerlite(task, klient=None):
    okres, blad = _okres(task, "mailerlite_report")
    if blad:
        return blad

    kontrakt = tool_registry.check_call("mailerlite_report",
                                        {"od": okres["od"].isoformat(), "do": okres["do"].isoformat()})
    if not kontrakt["allowed"]:
        return _odmowa(kontrakt["reason"], "mailerlite_report")

    try:
        klient = klient or get_mailerlite_client()
        kampanie, sprawdzono = klient.get_sent_campaigns(okres["od"], okres["do"])
    except MailerLiteNiedostepny as exc:
        return _odmowa(str(exc), "mailerlite_report")

    if any(k.get("mock") for k in kampanie):
        return _odmowa(
            "Dane pochodzą z klienta testowego MailerLite (zmyślone kampanie), a nie z konta firmowego — "
            "nie buduję z nich zestawienia. Ustaw MAILERLITE_API_KEY w app/secrets/.env.",
            "mailerlite_report")

    sciezka = _zapisz_surowe("mailerlite", {"okres": okres, "kampanie": kampanie})
    sygnatura = {"zrodlo": "mailerlite", "od": okres["od"].isoformat(), "do": okres["do"].isoformat(),
                 "kampanii_w_okresie": len(kampanie),
                 "id_kampanii": sorted(str(k["id"]) for k in kampanie)}

    if not kampanie:
        return {"cost_usd": 0.0, "tool": "mailerlite_report", "executed": True,
                "acceptance_notes": ("Zestawienie wysyłek MailerLite za okres %s\n\n"
                                     "W tym okresie nie wysłano żadnej kampanii. "
                                     "(Sprawdziłem %d wysłanych kampanii na koncie — żadna nie ma daty wysyłki "
                                     "z tego zakresu.)" % (okres["opis"], sprawdzono)),
                "source_note": "MailerLite, statystyki wysłanych kampanii (pobrano %s)" % datetime.now().strftime("%d.%m.%Y"),
                "output": sygnatura,
                "functional_checks": [{"name": "Surowa odpowiedź MailerLite zapisana na dysku",
                                       "type": "nonempty_file", "target": sciezka}]}

    material = "\n\n".join([
        "Zestawienie wysyłek MailerLite za okres %s" % okres["opis"],
        _tabela_kampanii(kampanie),
        _podsumowanie_liczbowe(kampanie),
    ])

    return {
        "cost_usd": 0.0,  # czysta arytmetyka na danych z API, bez modelu
        "tool": "mailerlite_report",
        "executed": True,
        "acceptance_notes": material,
        "source_note": "MailerLite, statystyki wysłanych kampanii (pobrano %s)" % datetime.now().strftime("%d.%m.%Y"),
        "output": sygnatura,
        "functional_checks": [{"name": "Surowa odpowiedź MailerLite zapisana na dysku",
                               "type": "nonempty_file", "target": sciezka}],
        # Rerun musi zwrócić DOKŁADNIE ten sam kształt co output — Bartek
        # porównuje sygnatury i inaczej każde zadanie wyglądałoby na losowe.
        "rerun": lambda: _sygnatura_mailerlite(klient, okres),
    }


def _sygnatura_mailerlite(klient, okres):
    kampanie, _ = klient.get_sent_campaigns(okres["od"], okres["do"])
    return {"zrodlo": "mailerlite", "od": okres["od"].isoformat(), "do": okres["do"].isoformat(),
            "kampanii_w_okresie": len(kampanie),
            "id_kampanii": sorted(str(k["id"]) for k in kampanie)}


# --------------------------------------------------------------------------
# Zanfia — podsumowanie sprzedaży kursów
# --------------------------------------------------------------------------

def podsumowanie_zanfia(task, klient=None):
    okres, blad = _okres(task, "zanfia_query")
    if blad:
        return blad

    kontrakt = tool_registry.check_call("zanfia_query",
                                        {"od": okres["od"].isoformat(), "do": okres["do"].isoformat()})
    if not kontrakt["allowed"]:
        return _odmowa(kontrakt["reason"], "zanfia_query")

    try:
        klient = klient or get_zanfia_client()
        wynik = klient.dane_sprzedazowe(okres["od"], okres["do"])
    except ZanfiaNiedostepna as exc:
        return _odmowa(str(exc), "zanfia_query")

    sciezka = _zapisz_surowe("zanfia", {"okres": okres, "wynik": wynik})
    sygnatura = {"zrodlo": "zanfia", "od": okres["od"].isoformat(), "do": okres["do"].isoformat(),
                 "narzedzie_mcp": wynik.get("narzedzie"), "argumenty": wynik.get("argumenty")}

    dane = wynik.get("dane")
    if dane in (None, [], {}):
        return _nie_wykonano(
            "Zanfia nie zwróciła żadnych danych sprzedażowych za okres %s (narzędzie MCP: %s)."
            % (okres["opis"], wynik.get("narzedzie")), "zanfia_query", sygnatura)

    # Kształt odpowiedzi zależy od serwera i nie jest znany z góry (kontrakt MCP
    # nie został jeszcze zweryfikowany na żywo), więc podsumowanie układa model
    # na podstawie surowych danych — tak samo jak dla treści pobranej ze strony.
    tresc = json.dumps(dane, ensure_ascii=False, indent=2, default=str)[:12000]
    pytanie = ("%s\n\nPodsumuj dane sprzedażowe za okres %s. Podawaj wyłącznie liczby obecne w danych; "
               "czego nie ma, napisz wprost, że tego nie ma."
               % (task.get("title", "Podsumowanie sprzedaży"), okres["opis"]))
    odpowiedz = web_answer.answer(pytanie, tresc, url="https://app.zanfia.com/mcp",
                                  zrodlo_opis="Zanfia, platforma sprzedaży kursów online")

    if not odpowiedz.get("available"):
        return _nie_wykonano(
            "pobrałem dane sprzedażowe z Zanfia, ale nie udało się z nich ułożyć podsumowania (%s). "
            "Surowe dane leżą w pliku %s." % (odpowiedz.get("detail", "brak modelu"), sciezka),
            "zanfia_query", sygnatura)

    return {
        "cost_usd": odpowiedz.get("cost_usd", 0.0),
        "tool": "zanfia_query",
        "executed": True,
        "acceptance_notes": odpowiedz["answer"],
        "source_note": "Zanfia, platforma sprzedaży kursów online (pobrano %s)" % datetime.now().strftime("%d.%m.%Y"),
        "output": sygnatura,
        "functional_checks": [{"name": "Surowa odpowiedź Zanfia zapisana na dysku",
                               "type": "nonempty_file", "target": sciezka}],
        "rerun": lambda: {"zrodlo": "zanfia", "od": okres["od"].isoformat(), "do": okres["do"].isoformat(),
                          "narzedzie_mcp": wynik.get("narzedzie"), "argumenty": wynik.get("argumenty")},
    }
