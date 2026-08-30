"""
Odczyt READ-ONLY witryn SharePoint tej samej organizacji — żądanie właściciela
29.08.2026: "każdy agent i subagent [ma mieć] do odczytu, bez zapisu,
oczywiście za wyjątkiem uprawnień do Zarządcze".

Warstwa POLITYKI nad sharepoint_client.py (czysta hydraulika Graph) — ten
moduł decyduje CO wolno przeczytać, sharepoint_client.py tylko wykonuje odczyt.

MODEL DOSTĘPU: ALLOWLIST, nie denylist — czytelne są WYŁĄCZNIE witryny wpisane
do rejestru `config/sharepoint_sites.yaml` (ten sam plik budowany już wcześniej
ręcznie przez właściciela: adresy witryn, do których aplikacja Graph ma
POTWIERDZONY dostęp — patrz jego nagłówek). Powód zmiany z pierwotnego
"denylist na całej organizacji" (29.08.2026, ta sama sesja): sprawdzone na
żywo, że aplikacja NIE MA Sites.Read.All (403 na site-search) — realnie umie
czytać TYLKO witryny z tego rejestru, więc denylist na "dowolnej" witrynie
dawałby fałszywe poczucie dostępu tam, gdzie i tak przyszłoby 403.
`config/sharepoint.yaml -> read_access.denied_site_paths` (np. "Zarządcze")
zostaje jako DODATKOWA warstwa (defense-in-depth) — nawet gdyby ktoś kiedyś
dopisał zakazaną witrynę do rejestru przez pomyłkę, denylist i tak zablokuje.

Zapis pozostaje WYŁĄCZNIE przez sharepoint_client.get_sharepoint_client()
(jedna, skonfigurowana witryna) — ten moduł nigdy nie woła upload_file/
ensure_folder.
"""

import re
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

import sharepoint_client

CONFIG_PATH = Path(__file__).parent / "config" / "sharepoint.yaml"
SITES_REGISTRY_PATH = Path(__file__).parent / "config" / "sharepoint_sites.yaml"

# Rozszerzenia traktowane jako plik tekstowy (read_text) — inaczej, brak
# rozszerzenia albo rozszerzenie binarne (.docx/.pdf/.xlsx) -> listing folderu.
TEXT_EXTENSIONS = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log"}


def _load_config():
    return yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}


def _load_sites_registry():
    return yaml.safe_load(SITES_REGISTRY_PATH.read_text(encoding="utf-8")) or {}


def _normalizuj(text):
    """Porównanie bez wielkości liter i polskich znaków diakrytycznych —
    "Zarządcze"/"Zarzadcze"/"ZARZĄDCZE" mają wyjść na to samo."""
    bez_diakrytykow = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return bez_diakrytykow.lower()


def find_registered_site(site_path, registry=None):
    """Wpis rejestru (config/sharepoint_sites.yaml -> sites) o dokładnie tym
    site_path, albo None gdy witryna nie jest zarejestrowana — czytelne są
    WYŁĄCZNIE zarejestrowane witryny (allowlist), patrz docstring modułu."""
    registry = registry if registry is not None else _load_sites_registry()
    aktualna = _normalizuj(site_path or "")
    for wpis in (registry.get("sites") or {}).values():
        if _normalizuj(wpis.get("site_path", "")) == aktualna:
            return wpis
    return None


def is_site_denied(site_path, config=None):
    """Dodatkowa warstwa (defense-in-depth) NIEZALEŻNA od rejestru allowlist —
    dokładne dopasowanie ALBO prefiks (np. '/sites/Zarzadcze/Podfolder' też
    wykluczony)."""
    config = config or _load_config()
    zakazane = [_normalizuj(p) for p in (config.get("read_access") or {}).get("denied_site_paths", [])]
    aktualna = _normalizuj(site_path or "")
    return any(aktualna == z or aktualna.startswith(z.rstrip("/") + "/") for z in zakazane)


def parse_sharepoint_url(url):
    """Rozkłada URL SharePoint na (site_host, site_path, remote_path) — zakłada
    standardowy układ Microsoft `https://<host>/sites/<nazwa>/<reszta>`. Zwraca
    None, gdy URL nie pasuje do tego układu (np. link 'sharing' ze skróconym
    tokenem zamiast realnej ścieżki) — wołający dostaje jawny komunikat zamiast
    zgadywania, na co URL wskazuje."""
    parsed = urlparse(url)
    if not parsed.hostname or not parsed.hostname.endswith(".sharepoint.com"):
        return None
    dopasowanie = re.match(r"^/sites/([^/]+)(/.*)?$", unquote(parsed.path))
    if not dopasowanie:
        return None
    nazwa_witryny, reszta = dopasowanie.group(1), dopasowanie.group(2) or ""
    # Segmenty typowe dla widoku biblioteki w przeglądarce (Forms/AllItems.aspx,
    # Shared%20Documents jako pierwszy segment biblioteki) — odcinamy je, żeby
    # zostać z realną ścieżką WEWNĄTRZ domyślnego drive'a, nie z adresem strony.
    segmenty = [s for s in reszta.strip("/").split("/") if s]
    if segmenty and segmenty[0].lower() in ("shared documents", "dokumenty"):
        segmenty = segmenty[1:]
    if segmenty and segmenty[-1].lower().startswith("allitems.aspx"):
        segmenty = segmenty[:-1]
    return {
        "site_host": parsed.hostname,
        "site_path": f"/sites/{nazwa_witryny}",
        "remote_path": "/".join(segmenty),
    }


def read_sharepoint_url(url):
    """Odczyt (listing folderu ALBO treść pliku tekstowego) pod adresem
    SharePoint — WYŁĄCZNIE dla witryn zarejestrowanych w
    config/sharepoint_sites.yaml (allowlist) i nie na liście wykluczeń
    (config/sharepoint.yaml -> read_access.denied_site_paths). Zwraca dict:
        {"available": bool, "detail": str, "kind": "listing"|"file"|None,
         "items": [...] albo None, "text": str albo None}
    Nigdy nie rzuca — błąd trafia do "detail", available=False (ten sam wzorzec
    co web_fetch_worker.fetch/browser_worker.run)."""
    rozlozony = parse_sharepoint_url(url)
    if not rozlozony:
        return {"available": False, "detail": f"Nie rozpoznano adresu SharePoint: '{url}' "
                                              "(oczekiwany układ https://<host>/sites/<nazwa>/...).",
                "kind": None, "items": None, "text": None}

    registry = _load_sites_registry()
    wlasny_host = registry.get("site_host")
    if wlasny_host and rozlozony["site_host"].lower() != wlasny_host.lower():
        return {"available": False,
                "detail": f"Host '{rozlozony['site_host']}' spoza organizacji "
                          f"('{wlasny_host}') — odczyt dozwolony wyłącznie w obrębie własnej organizacji.",
                "kind": None, "items": None, "text": None}

    if is_site_denied(rozlozony["site_path"]):
        return {"available": False,
                "detail": f"Witryna '{rozlozony['site_path']}' jest na liście wykluczeń "
                          "(config/sharepoint.yaml -> read_access.denied_site_paths) — odmowa.",
                "kind": None, "items": None, "text": None}

    wpis = find_registered_site(rozlozony["site_path"], registry)
    if wpis is None:
        return {"available": False,
                "detail": f"Witryna '{rozlozony['site_path']}' nie jest w rejestrze dostępnych witryn "
                          "(config/sharepoint_sites.yaml) — dopisz ją tam, jeśli aplikacja Graph ma "
                          "do niej dostęp, inaczej odczyt i tak zwróci 403.",
                "kind": None, "items": None, "text": None}

    client = sharepoint_client.get_sharepoint_client_for_site(
        rozlozony["site_host"], rozlozony["site_path"], library=wpis.get("library"))
    if client is None:
        return {"available": False, "detail": "Brak sekretów MS_GRAPH_*/msal — odczyt SharePoint niedostępny.",
                "kind": None, "items": None, "text": None}

    remote_path = rozlozony["remote_path"]
    wyglada_na_plik = bool(Path(remote_path).suffix)
    try:
        if wyglada_na_plik and Path(remote_path).suffix.lower() in TEXT_EXTENSIONS:
            text = client.read_text(remote_path)
            return {"available": True, "detail": f"Odczytano '{remote_path}'.",
                    "kind": "file", "items": None, "text": text}
        items = client.list_children(remote_path)
        return {"available": True, "detail": f"Wypisano zawartość '{remote_path or '/'}' ({len(items)} pozycji).",
                "kind": "listing", "items": items, "text": None}
    except sharepoint_client.SharePointWriteError as exc:
        return {"available": False, "detail": str(exc), "kind": None, "items": None, "text": None}
