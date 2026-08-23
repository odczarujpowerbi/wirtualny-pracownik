"""
Konektor do zanfia.com przez MCP (config/integrations.yaml wpis `zanfia_courses`)
— platforma sprzedaży kursów online.

Różnica wobec Projectly: tam WIEMY, jak nazywają się narzędzia MCP i co robią
(config/projectly.yaml), bo kontrakt został zweryfikowany na żywo. Tutaj NIE
wiemy — serwer odrzuca dziś autoryzację (HTTP 401), więc nawet tools/list nie
przeszło. Dlatego ten klient jest zbudowany na ODKRYWANIU: pyta serwer, jakie
ma narzędzia, i dopiero wtedy decyduje, których użyć. Gdy token zacznie
działać, nie trzeba zmieniać kodu — wystarczy, że discovery zwróci listę.

Dwie twarde zasady:
  1. TYLKO ODCZYT. Narzędzie, którego nazwa sugeruje zapis (create/update/
     delete/send/...), nie zostanie wywołane, choćby serwer je udostępniał
     i choćby model o to poprosił. Zadanie "podsumuj sprzedaż" nie ma prawa
     niczego zmienić na platformie sprzedażowej.
  2. Fail closed. Brak tokenu, 401, brak pasującego narzędzia -> wyjątek
     z powodem po polsku, który człowiek może przeczytać w Projectly
     i wiedzieć, co ma zrobić. Nigdy dane zastępcze.
"""

import os
import re

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env przed odczytem ZANFIA_MCP_*
from mcp_client import MCPClient, MCPError

# Czasowniki zapisu w nazwie narzędzia MCP. Dopasowanie = narzędzie odrzucone
# na naszym poziomie, niezależnie od uprawnień tokenu (obrona w głąb: token
# może mieć więcej praw, niż potrzebuje to zadanie).
CZASOWNIKI_ZAPISU = ("create", "add", "update", "edit", "set", "delete", "remove", "destroy",
                     "send", "post", "publish", "cancel", "refund", "charge", "import",
                     "upload", "enroll", "assign", "revoke", "reset", "write")

# Słowa, po których poznajemy narzędzie odpowiadające za dane sprzedażowe.
SLOWA_SPRZEDAZ = ("order", "sale", "sales", "purchase", "payment", "transaction",
                  "revenue", "invoice", "enrollment", "subscription", "zamowien", "sprzedaz")


class ZanfiaNiedostepna(RuntimeError):
    """Nie da się pobrać danych z Zanfia — brak konfiguracji, odmowa serwera,
    brak pasującego narzędzia. Powód jest sformułowany dla człowieka."""


def _tylko_odczyt(nazwa):
    n = (nazwa or "").lower()
    return not any(re.search(r"(^|[_\-.])" + cz, n) or n.startswith(cz) for cz in CZASOWNIKI_ZAPISU)


class ZanfiaClient:
    def __init__(self, base_url, token, timeout=30):
        self._mcp = MCPClient(base_url, token, client_name="wirtualny-pracownik/zanfia", timeout=timeout)
        self.base_url = base_url
        self._narzedzia = None

    def _blad_czytelny(self, exc, co_robiono):
        tekst = str(exc)
        if "HTTP 401" in tekst or "Unauthorized" in tekst:
            return ZanfiaNiedostepna(
                "Zanfia odrzuciła autoryzację (401) przy próbie " + co_robiono + ". Token ZANFIA_MCP_TOKEN "
                "z app/secrets/.env jest nieważny, wygasł albo serwer oczekuje innego sposobu uwierzytelnienia "
                "niż nagłówek 'Authorization: Bearer'. Do odblokowania potrzebny jest aktualny token MCP "
                "z panelu zanfia.com (i potwierdzenie, w jakim nagłówku go wysyłać).")
        if "HTTP 404" in tekst:
            return ZanfiaNiedostepna(
                "Pod adresem " + str(self.base_url) + " nie ma serwera MCP (404) — sprawdź ZANFIA_MCP_URL.")
        return ZanfiaNiedostepna("Zanfia nie odpowiedziała poprawnie przy próbie " + co_robiono + ": " + tekst[:200])

    def list_tools(self):
        """Narzędzia wystawiane przez serwer MCP. Wynik zapamiętany na czas życia
        obiektu — discovery to jedno zapytanie na zadanie, nie na wywołanie."""
        if self._narzedzia is not None:
            return self._narzedzia
        try:
            self._mcp._ensure_initialized()
            odpowiedz = self._mcp._rpc("tools/list", {})
        except MCPError as exc:
            raise self._blad_czytelny(exc, "odczytania listy narzędzi") from exc
        self._narzedzia = ((odpowiedz or {}).get("result") or {}).get("tools") or []
        return self._narzedzia

    def narzedzia_odczytu(self):
        return [t for t in self.list_tools() if _tylko_odczyt(t.get("name"))]

    def call(self, nazwa, argumenty=None):
        """Wywołanie narzędzia MCP — wyłącznie odczytowego."""
        if not _tylko_odczyt(nazwa):
            raise ZanfiaNiedostepna(
                "Odmowa: narzędzie '" + str(nazwa) + "' wygląda na zapisujące, a to zadanie ma prawo "
                "tylko czytać dane. Zmiany na platformie sprzedażowej wymagają decyzji człowieka.")
        try:
            return self._mcp.call_tool(nazwa, argumenty or {})
        except MCPError as exc:
            raise self._blad_czytelny(exc, "wywołania narzędzia '" + str(nazwa) + "'") from exc

    def znajdz_narzedzie_sprzedazy(self):
        """Które z odkrytych narzędzi odczytu odpowiada za dane sprzedażowe.
        Zwraca (narzedzie, None) albo (None, powod_odmowy) — nie zgadujemy
        w ciemno, bo wywołanie losowego narzędzia da losowe dane."""
        odczyt = self.narzedzia_odczytu()
        if not odczyt:
            return None, ("Serwer MCP Zanfia nie udostępnia żadnego narzędzia odczytu "
                          "(widoczne narzędzia: " + (", ".join(t.get("name", "?") for t in self.list_tools()) or "brak") + ").")
        for narzedzie in odczyt:
            tekst = (str(narzedzie.get("name", "")) + " " + str(narzedzie.get("description", ""))).lower()
            if any(slowo in tekst for slowo in SLOWA_SPRZEDAZ):
                return narzedzie, None
        return None, ("Wśród narzędzi odczytu Zanfia nie znalazłem takiego, które dotyczy sprzedaży/zamówień. "
                      "Dostępne: " + ", ".join(t.get("name", "?") for t in odczyt) + ". "
                      "Wskaż, które z nich ma być źródłem podsumowania sprzedaży.")

    def dane_sprzedazowe(self, od, do):
        """Surowe dane sprzedażowe za okres [od, do]. Nazwy parametrów narzędzia
        nie są znane z góry — dopasowujemy je do schematu zgłoszonego przez
        serwer (inputSchema), zamiast wysyłać zgadnięte klucze."""
        narzedzie, powod = self.znajdz_narzedzie_sprzedazy()
        if not narzedzie:
            raise ZanfiaNiedostepna(powod)
        argumenty = self._daty_wg_schematu(narzedzie, od, do)
        return {"narzedzie": narzedzie.get("name"), "argumenty": argumenty,
                "dane": self.call(narzedzie.get("name"), argumenty)}

    @staticmethod
    def _daty_wg_schematu(narzedzie, od, do):
        """Mapuje zakres dat na parametry, których narzędzie faktycznie oczekuje.
        Gdy narzędzie nie przyjmuje dat, zwracamy pusty zestaw — filtrowanie po
        dacie zrobimy wtedy po naszej stronie, na pobranych rekordach."""
        wlasciwosci = (narzedzie.get("inputSchema") or {}).get("properties") or {}
        argumenty = {}
        for nazwa in wlasciwosci:
            n = nazwa.lower()
            if any(k in n for k in ("from", "start", "since", "after", "od")):
                argumenty[nazwa] = od.isoformat()
            elif any(k in n for k in ("to", "end", "until", "before", "do")):
                argumenty[nazwa] = do.isoformat()
        return argumenty


def get_zanfia_client():
    """Fail closed: bez adresu i tokenu nie ma klienta."""
    url = os.environ.get("ZANFIA_MCP_URL")
    token = os.environ.get("ZANFIA_MCP_TOKEN")
    if not url or not token:
        raise ZanfiaNiedostepna(
            "Brak ZANFIA_MCP_URL lub ZANFIA_MCP_TOKEN w app/secrets/.env — nie mam się czym połączyć "
            "z platformą kursów zanfia.com.")
    return ZanfiaClient(url, token)


if __name__ == "__main__":
    from datetime import date, timedelta
    try:
        klient = get_zanfia_client()
        print("Narzędzia MCP Zanfia:")
        for t in klient.list_tools():
            znak = "R " if _tylko_odczyt(t.get("name")) else "W!"
            print("  " + znak + " " + str(t.get("name")) + " — " + str(t.get("description", ""))[:90])
        do = date.today() - timedelta(days=1)
        print(klient.dane_sprzedazowe(do - timedelta(days=6), do))
    except ZanfiaNiedostepna as exc:
        print("NIEDOSTĘPNE: " + str(exc))
