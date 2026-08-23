"""
Konektor do MailerLite REST API (config/integrations.yaml wpis `mailerlite`).

ZMIANA WOBEC PIERWSZEJ WERSJI (istotna dla bezpieczeństwa danych): brak klucza
API NIE degraduje już cicho do klienta mockowego. Stara wersja przy pustym
MAILERLITE_API_KEY zwracała MockMailerLiteClient z wymyślonymi kampaniami
("3 błędy w DAX", 2400 odbiorców) — worker zbudowałby z tego raport wyglądający
na prawdziwy i podał go człowiekowi jako zestawienie realnych wysyłek. To jest
dokładnie ten rodzaj cichej awarii, której zabrania zasada fail closed.
Teraz: brak klucza -> wyjątek MailerLiteNiedostepny z powodem po polsku, worker
eskaluje. Mock tylko na jawne żądanie (MAILERLITE_MOCK=1 albo get_mailerlite_client(mock=True)),
używany wyłącznie w testach dymnych.

UWAGA O KONTRAKCIE API: ścieżki i nazwy pól poniżej są zgodne z publicznym
API v2 (connect.mailerlite.com), ale NIE zostały zweryfikowane na żywo — na tej
maszynie nie ma jeszcze klucza. Dlatego czytanie statystyk jest TOLERANCYJNE
(_pole() sprawdza kilka wariantów nazwy), a każde pole, którego nie udało się
znaleźć, zostaje None, a nie 0 — zero wyglądałoby jak zmierzona wartość.
Pierwsze uruchomienie z realnym kluczem: sprawdź surową odpowiedź metodą
opisz_kontrakt() i dopiero wtedy zawężaj nazwy pól.
"""

import os
from datetime import date, datetime

import requests

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem MAILERLITE_API_KEY

BASE_URL = "https://connect.mailerlite.com/api"
LIMIT_STRONY = 50
MAX_STRON = 20  # zabezpieczenie przed pętlą, gdy API nie sygnalizuje końca


class MailerLiteNiedostepny(RuntimeError):
    """Nie da się pobrać danych z MailerLite — brak klucza, odmowa, błąd sieci.
    Niesie powód sformułowany dla człowieka (trafia do komentarza w Projectly)."""


def _pole(obj, *nazwy, domyslnie=None):
    """Pierwsza z podanych nazw, która realnie występuje w odpowiedzi. API bywa
    wersjonowane różnie (opens vs opens_count vs unique_opens_count) — zamiast
    zgadywać jedną nazwę, sprawdzamy warianty i uczciwie zwracamy None, gdy
    żadnego nie ma."""
    for nazwa in nazwy:
        if isinstance(obj, dict) and obj.get(nazwa) is not None:
            return obj[nazwa]
    return domyslnie


def _na_date(wartosc):
    """'2026-08-14 09:30:00' / '2026-08-14T09:30:00Z' -> date. None, gdy się nie da."""
    if isinstance(wartosc, date):
        return wartosc
    if not wartosc:
        return None
    tekst = str(wartosc).replace("T", " ").replace("Z", "").strip()
    for dlugosc, fmt in ((19, "%Y-%m-%d %H:%M:%S"), (16, "%Y-%m-%d %H:%M"), (10, "%Y-%m-%d")):
        try:
            return datetime.strptime(tekst[:dlugosc], fmt).date()
        except ValueError:
            continue
    return None


def _procent(licznik, mianownik):
    if not mianownik or licznik is None:
        return None
    return round(100.0 * licznik / mianownik, 2)


def normalizuj_kampanie(surowa):
    """Surowa kampania z API -> jeden wspólny kształt, na którym liczy raport.
    Pola nieodnalezione zostają None (nie 0) — brak pomiaru to nie jest zero."""
    stats = surowa.get("stats") or {}
    emails = surowa.get("emails") or []
    pierwszy_mail = emails[0] if emails and isinstance(emails[0], dict) else {}

    odbiorcy = _pole(stats, "sent", "sent_count", "recipients_count", "total_recipients")
    otwarcia = _pole(stats, "unique_opens_count", "opens_count", "unique_opens", "opens")
    klikniecia = _pole(stats, "unique_clicks_count", "clicks_count", "unique_clicks", "clicks")

    return {
        "id": surowa.get("id"),
        "nazwa": surowa.get("name"),
        "temat": _pole(surowa, "subject") or _pole(pierwszy_mail, "subject") or surowa.get("name"),
        # Tresc maila do analizy tonu/czytelnosci (mailerlite_report_analyzer.py) —
        # zweryfikowane na koncie produkcyjnym 24.08.2026: API daje tylko plain_text,
        # bez HTML w tym samym wywolaniu (potrzebny byloby osobny endpoint).
        "tresc_plain": _pole(pierwszy_mail, "plain_text"),
        "data_wysylki": _na_date(_pole(surowa, "finished_at", "sent_at", "delivered_at", "scheduled_for", "updated_at")),
        "odbiorcy": odbiorcy,
        "otwarcia": otwarcia,
        "klikniecia": klikniecia,
        "rezygnacje": _pole(stats, "unsubscribes_count", "unsubscribes"),
        "odbicia": _pole(stats, "bounces_count", "hard_bounces_count", "bounces"),
        "open_rate": _procent(otwarcia, odbiorcy),
        "ctr": _procent(klikniecia, odbiorcy),
        "surowe_stats_klucze": sorted(stats.keys()),
    }


class MailerLiteClient:
    def __init__(self, api_key, timeout=20):
        self.api_key = api_key
        self._timeout = timeout
        self._headers = {"Authorization": "Bearer " + api_key, "Accept": "application/json"}

    def _get(self, sciezka, params=None):
        try:
            r = requests.get(BASE_URL + sciezka, headers=self._headers, params=params, timeout=self._timeout)
        except requests.RequestException as exc:
            raise MailerLiteNiedostepny("Nie udało się połączyć z MailerLite: " + str(exc)) from exc
        if r.status_code == 401:
            raise MailerLiteNiedostepny(
                "MailerLite odrzucił klucz API (401). Klucz wygasł albo nie ma uprawnień do kampanii — "
                "wygeneruj nowy w MailerLite (Integrations -> API) i wpisz do secrets/.env jako MAILERLITE_API_KEY.")
        if r.status_code == 429:
            raise MailerLiteNiedostepny("MailerLite ograniczył liczbę zapytań (429) — spróbuj za kilka minut.")
        if r.status_code >= 400:
            raise MailerLiteNiedostepny(
                "MailerLite odpowiedział błędem %s na %s." % (r.status_code, sciezka))
        try:
            return r.json()
        except ValueError as exc:
            raise MailerLiteNiedostepny("MailerLite zwrócił odpowiedź, której nie da się odczytać jako JSON.") from exc

    def opisz_kontrakt(self):
        """Diagnostyka pierwszego uruchomienia: surowe klucze pierwszej kampanii.
        Do porównania z założeniami w tym pliku, ZANIM ktokolwiek zaufa liczbom."""
        dane = self._get("/campaigns", {"filter[status]": "sent", "limit": 1}).get("data", [])
        if not dane:
            return {"kampanii": 0, "klucze": [], "klucze_stats": []}
        return {"kampanii": 1, "klucze": sorted(dane[0].keys()),
                "klucze_stats": sorted((dane[0].get("stats") or {}).keys())}

    def _wszystkie_wyslane(self):
        """Wysłane kampanie, strona po stronie. MailerLite nie ma filtra 'od daty'
        dla kampanii — poprzednia wersja tego pliku wysyłała nieistniejący
        filter[since], który serwer po prostu ignorował, czyli filtr nie działał
        wcale. Zakres dat odcinamy po naszej stronie, na dacie wysyłki."""
        zebrane = []
        for strona in range(1, MAX_STRON + 1):
            odpowiedz = self._get("/campaigns", {"filter[status]": "sent", "limit": LIMIT_STRONY, "page": strona})
            partia = odpowiedz.get("data", [])
            zebrane.extend(partia)
            if len(partia) < LIMIT_STRONY:
                break
        return zebrane

    def get_sent_campaigns(self, od, do):
        """Kampanie wysłane w zakresie [od, do] (daty włącznie), znormalizowane.
        Zwraca (lista_kampanii, ile_wszystkich_wyslanych_sprawdzono)."""
        wszystkie = self._wszystkie_wyslane()
        w_okresie = []
        for surowa in wszystkie:
            rekord = normalizuj_kampanie(surowa)
            if rekord["data_wysylki"] and od <= rekord["data_wysylki"] <= do:
                w_okresie.append(rekord)
        w_okresie.sort(key=lambda k: k["data_wysylki"])
        return w_okresie, len(wszystkie)

    # --- zgodność wstecz z mailerlite_report_analyzer.py ---
    def get_campaigns_sent_since(self, since_iso_date):
        """Zgodność wsteczna ze starszym wywołaniem (data jako string) — delegacja
        do get_sent_campaigns(od, do), która ma już poprawną paginację i
        tolerancyjne parsowanie pól. `filter[since]` NIE istnieje w REST
        MailerLite (zweryfikowane na koncie produkcyjnym 22.08.2026, wcześniejsza
        wersja wysyłała ten parametr i dostawała 400) — data jest filtrowana po
        stronie klienta, co get_sent_campaigns już robi."""
        od = _na_date(since_iso_date) or date.min
        kampanie, _ = self.get_sent_campaigns(od, date.today())
        return kampanie

    def get_campaign_stats(self, campaign_id):
        return normalizuj_kampanie(self._get("/campaigns/" + str(campaign_id)).get("data", {}))


class MockMailerLiteClient:
    """WYŁĄCZNIE do testów dymnych. Dane są zmyślone, więc każdy rekord niesie
    flagę `mock: True` — worker odmawia budowania raportu z takich danych, żeby
    zmyślone liczby nie mogły trafić do człowieka jako realne."""

    def __init__(self, campaigns_path=None):
        from pathlib import Path
        self.campaigns_path = campaigns_path or Path(__file__).parent / "mock_data" / "sample_mailerlite_campaigns.json"

    def _wczytaj(self):
        import json
        with open(self.campaigns_path, encoding="utf-8") as f:
            return json.load(f)

    def get_sent_campaigns(self, od, do):
        kampanie = []
        for c in self._wczytaj():
            kampanie.append({
                "mock": True,
                "id": c.get("id"),
                "nazwa": c.get("subject"),
                "temat": c.get("subject"),
                "data_wysylki": od,
                "odbiorcy": c.get("sent_count"),
                "otwarcia": c.get("opens"),
                "klikniecia": c.get("clicks"),
                "rezygnacje": None,
                "odbicia": None,
                "open_rate": _procent(c.get("opens"), c.get("sent_count")),
                "ctr": _procent(c.get("clicks"), c.get("sent_count")),
                "surowe_stats_klucze": [],
            })
        return kampanie, len(kampanie)

    def get_campaigns_sent_since(self, since_iso_date):
        kampanie, _ = self.get_sent_campaigns(_na_date(since_iso_date) or date.min, date.today())
        return kampanie

    def get_campaign_stats(self, campaign_id):
        for c in self.get_campaigns_sent_since(None):
            if c["id"] == campaign_id:
                return c
        return {}


def get_mailerlite_client(mock=False):
    """Fail closed: bez klucza NIE ma klienta. Mock tylko na jawne żądanie."""
    if mock or os.environ.get("MAILERLITE_MOCK") == "1":
        return MockMailerLiteClient()
    api_key = os.environ.get("MAILERLITE_API_KEY")
    if not api_key:
        raise MailerLiteNiedostepny(
            "Brak klucza MAILERLITE_API_KEY w app/secrets/.env — nie mam czym pobrać danych z MailerLite. "
            "Nie buduję raportu z danych zastępczych, bo wyglądałby jak prawdziwy. "
            "Żeby to odblokować: MailerLite -> Integrations -> API -> wygeneruj token i wpisz go do secrets/.env.")
    return MailerLiteClient(api_key)
