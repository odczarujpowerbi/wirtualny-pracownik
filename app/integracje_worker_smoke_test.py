"""
Test dymny workerów integracyjnych: MailerLite (zestawienie wysyłek) i Zanfia
(podsumowanie sprzedaży). CELOWO BEZ SIECI — konektory są wstrzykiwane atrapami
zwracającymi kształt odpowiedzi taki, jaki deklaruje dokumentacja API/MCP.

Ten test pilnuje przede wszystkim rzeczy, których nie widać w happy pathu:
  - brak klucza / odmowa serwera kończy się ODMOWĄ z powodem, nie raportem,
  - dane z klienta mockowego NIGDY nie zbudują materiału dla człowieka,
  - brak okresu w zadaniu to odmowa, nie domyślne "ostatnie 7 dni",
  - kampania bez kompletu statystyk nie wpada do sum jako zero,
  - narzędzie MCP z czasownikiem zapisu nie zostanie wywołane.

Użycie:
    python integracje_worker_smoke_test.py
"""

import sys
from datetime import date

import executor
import integracje_worker
import period_resolver
import risk_hint
import zanfia_client
from mailerlite_client import MailerLiteNiedostepny, normalizuj_kampanie
from zanfia_client import ZanfiaNiedostepna

DZIS = date(2026, 8, 20)

# Kształt zgodny z API v2 MailerLite: statystyki w zagnieżdżonym "stats",
# temat w "emails"[0], data wysyłki w "finished_at".
SUROWE_KAMPANIE = [
    {"id": "111", "name": "Newsletter 33", "finished_at": "2026-08-14 09:30:00",
     "emails": [{"subject": "3 błędy w DAX, które kosztują Cię godziny"}],
     "stats": {"sent": 2400, "unique_opens_count": 840, "unique_clicks_count": 96,
               "unsubscribes_count": 5, "bounces_count": 12}},
    {"id": "222", "name": "Zaproszenie na webinar", "finished_at": "2026-08-18 11:00:00",
     "emails": [{"subject": "Webinar: Power BI w praktyce"}],
     "stats": {"sent": 2380, "unique_opens_count": 1020, "unique_clicks_count": 210,
               "unsubscribes_count": 3, "bounces_count": 8}},
    # Kampania z niepełnymi statystykami — nie wolno jej policzyć jako zera.
    {"id": "333", "name": "Test A/B", "finished_at": "2026-08-17 08:00:00",
     "emails": [{"subject": "Krótki test"}], "stats": {}},
    # Poza okresem — nie może trafić do zestawienia.
    {"id": "444", "name": "Stary mail", "finished_at": "2026-07-02 10:00:00",
     "emails": [{"subject": "Lipcowy newsletter"}],
     "stats": {"sent": 2000, "unique_opens_count": 500, "unique_clicks_count": 40}},
]


class AtrapaMailerLite:
    def get_sent_campaigns(self, od, do):
        wszystkie = [normalizuj_kampanie(s) for s in SUROWE_KAMPANIE]
        w_okresie = sorted([k for k in wszystkie if k["data_wysylki"] and od <= k["data_wysylki"] <= do],
                           key=lambda k: k["data_wysylki"])
        return w_okresie, len(wszystkie)


class AtrapaMailerLitePusta:
    def get_sent_campaigns(self, od, do):
        return [], 7


class AtrapaMailerLiteMock:
    def get_sent_campaigns(self, od, do):
        return [{"mock": True, "id": "ML-001", "temat": "Zmyślona kampania", "data_wysylki": od,
                 "odbiorcy": 2400, "otwarcia": 840, "klikniecia": 96, "rezygnacje": None,
                 "odbicia": None, "open_rate": 35.0, "ctr": 4.0}], 1


class AtrapaMailerLiteOdmowa:
    def get_sent_campaigns(self, od, do):
        raise MailerLiteNiedostepny("MailerLite odrzucił klucz API (401).")


class AtrapaZanfia:
    def __init__(self, narzedzia):
        self._narzedzia = narzedzia

    def list_tools(self):
        return self._narzedzia

    def narzedzia_odczytu(self):
        return [t for t in self._narzedzia if zanfia_client._tylko_odczyt(t.get("name"))]

    znajdz_narzedzie_sprzedazy = zanfia_client.ZanfiaClient.znajdz_narzedzie_sprzedazy
    _daty_wg_schematu = staticmethod(zanfia_client.ZanfiaClient._daty_wg_schematu)

    def call(self, nazwa, argumenty=None):
        return {"orders": [{"course": "Power BI od zera", "amount": 499, "date": "2026-08-15"}]}

    def dane_sprzedazowe(self, od, do):
        return zanfia_client.ZanfiaClient.dane_sprzedazowe(self, od, do)


class AtrapaZanfiaOdmowa:
    def dane_sprzedazowe(self, od, do):
        raise ZanfiaNiedostepna("Zanfia odrzuciła autoryzację (401) przy próbie odczytania listy narzędzi.")


ZADANIE_ML = {"task_id": "T-ML", "title": "Zestawienie wysyłek kampanii z MailerLite za ostatni tydzień",
              "description": "temat, data, liczba odbiorców, open rate, CTR"}
ZADANIE_ZAN = {"task_id": "T-ZAN", "title": "Podsumowanie sprzedaży kursów z Zanfia za ostatni tydzień",
               "description": ""}


def run():
    checks = []

    # --- okres ---
    okres = period_resolver.resolve("za ostatni tydzień", DZIS)
    checks.append(("Okres 'ostatni tydzień' to 7 pełnych dni do wczoraj włącznie",
                   okres["od"] == date(2026, 8, 13) and okres["do"] == date(2026, 8, 19)))
    checks.append(("Okres ma opis dla człowieka, nie samą frazę względną",
                   okres["opis"] == "13-19 sierpnia 2026"))
    checks.append(("Brak wskazówki o okresie -> None (nie domyślne 7 dni)",
                   period_resolver.resolve("zrób zestawienie wysyłek", DZIS) is None))

    # --- MailerLite: happy path ---
    wynik = integracje_worker.raport_mailerlite(ZADANIE_ML, klient=AtrapaMailerLite(), dzis=DZIS)
    material = wynik["acceptance_notes"]
    checks.append(("MailerLite: zadanie wykonane", wynik["executed"] is True))
    checks.append(("MailerLite: materiał nazywa konkretny okres, nie 'ostatni tydzień'",
                   "13-19 sierpnia 2026" in material and "ostatni tydzień" not in material))
    checks.append(("MailerLite: kampania spoza okresu odfiltrowana",
                   "Lipcowy newsletter" not in material and "444" not in str(wynik["output"]["id_kampanii"])))
    checks.append(("MailerLite: w zestawieniu są 3 kampanie z okresu",
                   wynik["output"]["kampanii_w_okresie"] == 3))
    checks.append(("MailerLite: open rate policzony z unikalnych otwarć (840/2400 = 35,0%)",
                   "35,0%" in material))
    checks.append(("MailerLite: brak statystyk pokazany jako '—', nie jako 0",
                   "| — | — | — | — | — |" in material))
    checks.append(("MailerLite: sumy pomijają kampanię bez danych i mówią o tym wprost",
                   "Łącznie: 2 wysyłki" in material and "Pominięto w sumach 1 kampanię" in material))
    checks.append(("MailerLite: pochodzenie danych osobnym polem, nie w materiale",
                   "MailerLite" in wynik["source_note"] and "źródło" not in material.lower()))
    checks.append(("MailerLite: efekt ma kontrolę funkcjonalną na zapisanym pliku",
                   wynik["functional_checks"][0]["type"] == "nonempty_file"))
    checks.append(("MailerLite: rerun() zwraca dokładnie ten sam kształt co output",
                   wynik["rerun"]() == wynik["output"]))
    checks.append(("MailerLite: raport bez modelu nie generuje kosztu", wynik["cost_usd"] == 0.0))

    # --- MailerLite: przypadki brzegowe ---
    pusty = integracje_worker.raport_mailerlite(ZADANIE_ML, klient=AtrapaMailerLitePusta(), dzis=DZIS)
    checks.append(("MailerLite: zero wysyłek to poprawny wynik, nie błąd",
                   pusty["executed"] is True and "nie wysłano żadnej kampanii" in pusty["acceptance_notes"]))

    z_mocka = integracje_worker.raport_mailerlite(ZADANIE_ML, klient=AtrapaMailerLiteMock(), dzis=DZIS)
    checks.append(("MailerLite: dane z mocka NIE budują materiału (odmowa)",
                   z_mocka["executed"] is False and "testowego" in z_mocka["acceptance_notes"]))

    odmowa = integracje_worker.raport_mailerlite(ZADANIE_ML, klient=AtrapaMailerLiteOdmowa(), dzis=DZIS)
    checks.append(("MailerLite: 401 kończy się odmową z powodem, nie raportem",
                   odmowa["executed"] is False and "401" in odmowa["acceptance_notes"]))

    bez_okresu = integracje_worker.raport_mailerlite(
        {"task_id": "T", "title": "Zestawienie wysyłek MailerLite"}, klient=AtrapaMailerLite())
    checks.append(("MailerLite: brak okresu w zadaniu -> odmowa z prośbą o doprecyzowanie",
                   bez_okresu["executed"] is False and "okres" in bez_okresu["acceptance_notes"]))

    # --- Zanfia ---
    narzedzia_ok = [{"name": "list_courses", "description": "Lista kursów"},
                    {"name": "get_orders", "description": "Zamówienia (sales) w okresie",
                     "inputSchema": {"properties": {"dateFrom": {}, "dateTo": {}}}}]
    klient_zan = AtrapaZanfia(narzedzia_ok)
    narzedzie, powod = klient_zan.znajdz_narzedzie_sprzedazy()
    checks.append(("Zanfia: discovery wybiera narzędzie sprzedażowe, nie pierwsze z brzegu",
                   narzedzie is not None and narzedzie["name"] == "get_orders"))
    checks.append(("Zanfia: zakres dat mapowany na parametry ze schematu narzędzia",
                   klient_zan._daty_wg_schematu(narzedzie, date(2026, 8, 13), date(2026, 8, 19))
                   == {"dateFrom": "2026-08-13", "dateTo": "2026-08-19"}))

    tylko_zapis = AtrapaZanfia([{"name": "create_order", "description": "Tworzy zamówienie (sale)"}])
    _, powod_zapis = tylko_zapis.znajdz_narzedzie_sprzedazy()
    checks.append(("Zanfia: narzędzie zapisujące odrzucone mimo pasującego opisu",
                   powod_zapis is not None and "odczytu" in powod_zapis))
    checks.append(("Zanfia: filtr odczytu przepuszcza get/list, blokuje create/update/delete",
                   all(zanfia_client._tylko_odczyt(n) for n in ("get_orders", "list_courses", "sales_summary"))
                   and not any(zanfia_client._tylko_odczyt(n) for n in ("create_order", "update_student",
                                                                        "delete_course", "send_email"))))

    zan_odmowa = integracje_worker.podsumowanie_zanfia(ZADANIE_ZAN, klient=AtrapaZanfiaOdmowa(), dzis=DZIS)
    checks.append(("Zanfia: 401 kończy się odmową z powodem po polsku",
                   zan_odmowa["executed"] is False and "401" in zan_odmowa["acceptance_notes"]))

    original = integracje_worker.web_answer.answer
    try:
        integracje_worker.web_answer.answer = lambda *a, **k: {
            "available": True, "answer": "W okresie 13-19 sierpnia 2026 sprzedano 1 kurs za 499 zł.",
            "cost_usd": 0.002, "source": None, "detail": ""}
        zan_ok = integracje_worker.podsumowanie_zanfia(ZADANIE_ZAN, klient=klient_zan, dzis=DZIS)
        checks.append(("Zanfia: happy path zwraca podsumowanie i sygnaturę z nazwą narzędzia MCP",
                       zan_ok["executed"] is True and zan_ok["output"]["narzedzie_mcp"] == "get_orders"))
        checks.append(("Zanfia: koszt modelu jest raportowany", zan_ok["cost_usd"] == 0.002))
    finally:
        integracje_worker.web_answer.answer = original

    # --- klasyfikacja ryzyka: rozpoznany worker read-only bije słowa w tytule ---
    def _kolor(tytul):
        z = {"title": tytul, "description": ""}
        return risk_hint.hint_from_task(z, executor.rozpoznaj_narzedzie(z))

    checks.append(("Ryzyko: zestawienie wysyłek kampanii to ZIELONE (odczyt), mimo słów 'wysyłk'/'kampani'",
                   _kolor("Zestawienie wysyłek kampanii z MailerLite za ostatni tydzień") == "green"))
    checks.append(("Ryzyko: podsumowanie sprzedaży z Zanfia to ZIELONE",
                   _kolor("Podsumowanie sprzedaży kursów z Zanfia za ostatni tydzień") == "green"))
    checks.append(("Ryzyko: 'zrób zestawienie I WYŚLIJ' zostaje CZERWONE (worker zrobiłby tylko połowę)",
                   _kolor("Zrób zestawienie wysyłek z MailerLite i wyślij je do Aldony") == "red"))
    checks.append(("Ryzyko: 'wyślij kampanię' zostaje CZERWONE",
                   _kolor("Wyślij kampanię do listy głównej w MailerLite") == "red"))
    checks.append(("Ryzyko: zadanie bez rozpoznanego workera ocenia heurystyka (budżet = czerwone)",
                   _kolor("Zwiększ budżet kampanii Meta o 20%") == "red"))
    checks.append(("risk_hint nie wywraca się na liście w acceptance_criteria",
                   risk_hint.hint_from_task({"title": "Sprawdź plik", "description": "",
                                             "acceptance_criteria": ["kryterium A", "kryterium B"]}) == "green"))

    print("\n--- Wynik testu dymnego integracje_worker ---")
    all_passed = True
    for name, passed in checks:
        print(("OK   " if passed else "BLAD ") + name)
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
