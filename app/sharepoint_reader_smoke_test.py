"""
Test dymny sharepoint_reader.py — odczyt READ-ONLY witryn SharePoint firmowej
organizacji, ALLOWLIST (config/sharepoint_sites.yaml — rejestr witryn z
potwierdzonym dostępem aplikacji Graph, dostarczony przez właściciela), z
DODATKOWYM wykluczeniem "Zarządcze" (config/sharepoint.yaml -> read_access).

Zero sieci: sharepoint_client.get_sharepoint_client_for_site podmieniony
atrapą. config/sharepoint.yaml i config/sharepoint_sites.yaml czytane
PRAWDZIWE — to jest test integracji z realnymi plikami configu, nie tylko logiki
(m.in. "SprzedazMarketing" MUSI być w rejestrze, "Zarzadcze" MUSI być wykluczone).

Użycie:
    python sharepoint_reader_smoke_test.py
"""

import sys

import sharepoint_client
import sharepoint_reader as sr

# Prawdziwa, zarejestrowana witryna (config/sharepoint_sites.yaml) — używana
# jako przykład "dozwolona witryna" we wszystkich testach happy-path poniżej.
DOZWOLONA_WITRYNA = "/sites/SprzedazMarketing"


class _FakeSharePointClient:
    def __init__(self, listing=None, files=None, raise_on=None):
        self.listing = listing or []
        self.files = files or {}
        self.raise_on = raise_on or set()

    def list_children(self, remote_path=""):
        if remote_path in self.raise_on:
            raise sharepoint_client.SharePointWriteError(f"403 Forbidden dla '{remote_path}'.")
        return self.listing

    def read_text(self, remote_path):
        if remote_path in self.raise_on:
            raise sharepoint_client.SharePointWriteError(f"403 Forbidden dla '{remote_path}'.")
        return self.files.get(remote_path, "")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_factory = sharepoint_client.get_sharepoint_client_for_site

    try:
        # --- 1. parse_sharepoint_url: rozkład standardowego adresu /sites/<nazwa>/... ---
        rozlozony = sr.parse_sharepoint_url(
            f"https://odczarujlowcode.sharepoint.com{DOZWOLONA_WITRYNA}/Shared%20Documents/Umowy/umowa.md")
        checks.append(("parse_sharepoint_url: rozpoznaje host/site_path/remote_path",
                       rozlozony == {"site_host": "odczarujlowcode.sharepoint.com",
                                    "site_path": DOZWOLONA_WITRYNA, "remote_path": "Umowy/umowa.md"}))

        rozlozony_root = sr.parse_sharepoint_url(f"https://odczarujlowcode.sharepoint.com{DOZWOLONA_WITRYNA}/")
        checks.append(("parse_sharepoint_url: sam root witryny -> remote_path pusty",
                       rozlozony_root["remote_path"] == ""))

        checks.append(("parse_sharepoint_url: obcy host (nie .sharepoint.com) -> None",
                       sr.parse_sharepoint_url("https://example.com/sites/X") is None))
        checks.append(("parse_sharepoint_url: sharepoint.com bez /sites/... -> None",
                       sr.parse_sharepoint_url("https://odczarujlowcode.sharepoint.com/losowa/sciezka") is None))

        # --- 2. find_registered_site / is_site_denied: rejestr (allowlist) +
        # dodatkowe wykluczenie (denylist), odporne na wielkość liter/ogonki. ---
        checks.append(("find_registered_site: prawdziwa witryna z rejestru -> wpis znaleziony",
                       sr.find_registered_site(DOZWOLONA_WITRYNA) is not None))
        checks.append(("find_registered_site: witryna spoza rejestru -> None",
                       sr.find_registered_site("/sites/NieistniejacaWitryna") is None))
        checks.append(("is_site_denied: '/sites/Zarzadcze' (config, bez ogonków) -> True",
                       sr.is_site_denied("/sites/Zarzadcze")))
        checks.append(("is_site_denied: '/sites/ZARZĄDCZE' (wielkość liter + ogonek) -> True",
                       sr.is_site_denied("/sites/ZARZĄDCZE")))
        checks.append(("is_site_denied: podfolder zakazanej witryny też wykluczony",
                       sr.is_site_denied("/sites/Zarzadcze/Finanse")))
        checks.append(("is_site_denied: dozwolona witryna -> False",
                       sr.is_site_denied(DOZWOLONA_WITRYNA) is False))

        # --- 3. read_sharepoint_url: witryna zakazana -> odmowa, BEZ wołania klienta. ---
        wolania = []
        sharepoint_client.get_sharepoint_client_for_site = (
            lambda *a, **k: wolania.append((a, k)) or _FakeSharePointClient())
        wynik_zakazane = sr.read_sharepoint_url(
            "https://odczarujlowcode.sharepoint.com/sites/Zarzadcze/Shared%20Documents/plan.md")
        checks.append(("read_sharepoint_url: witryna 'Zarzadcze' -> available=False, BRAK wołania klienta",
                       wynik_zakazane["available"] is False and wolania == []))
        checks.append(("read_sharepoint_url: odmowa niesie powód (lista wykluczeń)",
                       "wykluczeń" in wynik_zakazane["detail"]))

        # --- 3b. read_sharepoint_url: witryna NIE w rejestrze (allowlist) ->
        # odmowa, BEZ wołania klienta — nawet gdy nie jest jawnie zakazana. ---
        wynik_niezarejestrowana = sr.read_sharepoint_url(
            "https://odczarujlowcode.sharepoint.com/sites/NieistniejacaWitryna/plik.md")
        checks.append(("read_sharepoint_url: witryna spoza rejestru -> available=False, BRAK wołania klienta",
                       wynik_niezarejestrowana["available"] is False and wolania == []))
        checks.append(("read_sharepoint_url: odmowa niesie powód (brak w rejestrze)",
                       "rejestrze" in wynik_niezarejestrowana["detail"]))

        # --- 4. read_sharepoint_url: witryna DOZWOLONA (w rejestrze), plik
        # tekstowy -> odczyt treści. ---
        sharepoint_client.get_sharepoint_client_for_site = (
            lambda *a, **k: _FakeSharePointClient(files={"Umowy/umowa.md": "Treść umowy testowej."}))
        wynik_plik = sr.read_sharepoint_url(
            f"https://odczarujlowcode.sharepoint.com{DOZWOLONA_WITRYNA}/Shared%20Documents/Umowy/umowa.md")
        checks.append(("read_sharepoint_url: witryna dozwolona, plik .md -> available=True, kind='file'",
                       wynik_plik["available"] is True and wynik_plik["kind"] == "file"))
        checks.append(("read_sharepoint_url: treść pliku w wyniku",
                       wynik_plik["text"] == "Treść umowy testowej."))

        # --- 5. read_sharepoint_url: witryna dozwolona, folder -> listing. ---
        sharepoint_client.get_sharepoint_client_for_site = (
            lambda *a, **k: _FakeSharePointClient(listing=[
                {"name": "umowa.docx", "is_folder": False, "web_url": "https://x/umowa.docx"},
                {"name": "Archiwum", "is_folder": True, "web_url": "https://x/Archiwum"},
            ]))
        wynik_folder = sr.read_sharepoint_url(
            f"https://odczarujlowcode.sharepoint.com{DOZWOLONA_WITRYNA}/Shared%20Documents/Umowy")
        checks.append(("read_sharepoint_url: folder (bez rozszerzenia pliku tekstowego) -> kind='listing'",
                       wynik_folder["available"] is True and wynik_folder["kind"] == "listing"
                       and len(wynik_folder["items"]) == 2))

        # --- 6. read_sharepoint_url: URL nierozpoznany -> available=False, jawny powód. ---
        wynik_zle = sr.read_sharepoint_url("https://example.com/cokolwiek")
        checks.append(("read_sharepoint_url: URL spoza wzorca SharePoint -> available=False",
                       wynik_zle["available"] is False and "Nie rozpoznano" in wynik_zle["detail"]))

        # --- 7. read_sharepoint_url: błąd Graph (403, np. brak faktycznie
        # nadanego dostępu mimo wpisu w rejestrze) -> available=False, powód
        # z wyjątku, nie wyjątek. ---
        sharepoint_client.get_sharepoint_client_for_site = (
            lambda *a, **k: _FakeSharePointClient(raise_on={"Umowy"}))
        wynik_403 = sr.read_sharepoint_url(
            f"https://odczarujlowcode.sharepoint.com{DOZWOLONA_WITRYNA}/Shared%20Documents/Umowy")
        checks.append(("read_sharepoint_url: błąd Graph (403) -> available=False, BEZ wyjątku",
                       wynik_403["available"] is False and "403" in wynik_403["detail"]))
    finally:
        sharepoint_client.get_sharepoint_client_for_site = original_factory

    print("\n--- Wynik testu dymnego sharepoint_reader ---")
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
