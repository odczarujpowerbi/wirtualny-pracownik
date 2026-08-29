"""
Konektor Microsoft Graph do zapisu plików na SharePoint (integrations.yaml
wpis `microsoft_365`) — zapis dokumentów wygenerowanych przez agenta
(document_builder.py, report_builder.py) do biblioteki `Wirtualny-pracownik`,
jeden folder per zadanie.

Ten sam przepływ app-only (client credentials) i te same zmienne środowiskowe
(MS_GRAPH_CLIENT_ID/SECRET/TENANT_ID) co microsoft_graph_mail_client.py —
osobny plik, bo to inne uprawnienie aplikacyjne (Sites.ReadWrite.All lub
Files.ReadWrite.All, z admin consent), nie Mail.Send.

Zależności: `msal` + `requests` (już w requirements.txt dla Graph). Import
obu LENIWY (wewnątrz metod) — ten sam wzorzec co microsoft_graph_mail_client.py.

BEZPIECZEŃSTWO: ten moduł nie decyduje SAM, czy zapis jest dozwolony — to
robi warstwa wyżej (approval_policy.yaml `sharepoint_upload` = yellow,
tool_contracts.yaml `allowed_domains`). Ten moduł to czysta hydraulika Graph.
"""

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}"
SCOPE = ["https://graph.microsoft.com/.default"]
HTTP_TIMEOUT_SECONDS = 30


class SharePointAuthError(RuntimeError):
    """Nie udało się uzyskać tokenu (zła konfiguracja aplikacji/uprawnień)."""


class SharePointWriteError(RuntimeError):
    """Graph odrzucił odczyt/zapis (kod != 2xx nieoczekiwany)."""


def msal_available():
    try:
        import msal  # noqa: F401
        return True
    except ImportError:
        return False


class SharePointClient:
    """Trzyma dane dostępowe i (leniwie) aplikację MSAL + id drive'a
    (cache'owane po pierwszym resolve_drive() — nie zmienia się w trakcie procesu)."""

    def __init__(self, client_id, client_secret, tenant_id, site_host, site_path, library=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.site_host = site_host
        self.site_path = site_path
        self.library = library
        self._app = None
        self._drive_id = None
        self._drive_web_url = None

    def _get_app(self):
        import msal
        if self._app is None:
            self._app = msal.ConfidentialClientApplication(
                self.client_id,
                authority=AUTHORITY_TEMPLATE.format(tenant_id=self.tenant_id),
                client_credential=self.client_secret,
            )
        return self._app

    def _acquire_token(self):
        app = self._get_app()
        result = app.acquire_token_silent(SCOPE, account=None) or app.acquire_token_for_client(scopes=SCOPE)
        if "access_token" not in result:
            raise SharePointAuthError(
                f"Nie uzyskano tokenu Graph: {result.get('error')} — "
                f"{(result.get('error_description') or '')[:200]}"
            )
        return result["access_token"]

    def _request(self, method, url, **kwargs):
        import requests

        token = self._acquire_token()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {token}"
        response = requests.request(method, url, headers=headers, timeout=HTTP_TIMEOUT_SECONDS, **kwargs)
        return response

    def resolve_drive(self):
        """GET site -> GET drive domyślny (lub dopasowany do self.library po nazwie).
        Wynik cache'owany w instancji — kolejne wywołania nie robią kolejnych GET."""
        if self._drive_id:
            return self._drive_id

        site_url = f"{GRAPH_BASE}/sites/{self.site_host}:{self.site_path}"
        site_resp = self._request("GET", site_url)
        if site_resp.status_code != 200:
            raise SharePointWriteError(f"Nie znaleziono witryny {site_url}: {site_resp.status_code} {site_resp.text[:300]}")
        site_id = site_resp.json()["id"]

        if self.library:
            drives_resp = self._request("GET", f"{GRAPH_BASE}/sites/{site_id}/drives")
            if drives_resp.status_code != 200:
                raise SharePointWriteError(f"Nie udało się wypisać bibliotek: {drives_resp.status_code} {drives_resp.text[:300]}")
            drives = drives_resp.json().get("value", [])
            match = next((d for d in drives if d.get("name") == self.library), None)
            if not match:
                dostepne = ", ".join(d.get("name", "") for d in drives)
                raise SharePointWriteError(f"Nie znaleziono biblioteki '{self.library}'. Dostępne: {dostepne}")
            drive = match
        else:
            drive_resp = self._request("GET", f"{GRAPH_BASE}/sites/{site_id}/drive")
            if drive_resp.status_code != 200:
                raise SharePointWriteError(f"Nie udało się odczytać domyślnego drive'a: {drive_resp.status_code} {drive_resp.text[:300]}")
            drive = drive_resp.json()

        self._drive_id = drive["id"]
        self._drive_web_url = drive.get("webUrl", "")
        return self._drive_id

    def _children_url(self, parent_path):
        drive_id = self.resolve_drive()
        parent_path = parent_path.strip("/")
        if not parent_path:
            return f"{GRAPH_BASE}/drives/{drive_id}/root/children"
        return f"{GRAPH_BASE}/drives/{drive_id}/root:/{parent_path}:/children"

    def ensure_folder(self, remote_path):
        """Tworzy folder (i wszystkie brakujące segmenty nadrzędne) — idempotentne,
        409 (już istnieje) traktowane jako sukces, nie błąd."""
        parts = [p for p in remote_path.strip("/").split("/") if p]
        built = ""
        for part in parts:
            parent = built
            resp = self._request("POST", self._children_url(parent), json={
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            })
            if resp.status_code not in (201, 409):
                raise SharePointWriteError(f"Nie udało się utworzyć folderu '{part}': {resp.status_code} {resp.text[:300]}")
            built = f"{built}/{part}" if built else part
        return built

    def upload_file(self, local_path, remote_path):
        """PUT z zawartością pliku (upload prosty, <4MB — dokumenty tej klasy są małe)."""
        drive_id = self.resolve_drive()
        remote_path = remote_path.strip("/")
        with open(local_path, "rb") as f:
            content = f.read()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_path}:/content"
        resp = self._request("PUT", url, data=content, headers={"Content-Type": "application/octet-stream"})
        if resp.status_code not in (200, 201):
            raise SharePointWriteError(f"Nie udało się wgrać '{remote_path}': {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def get_item(self, remote_path):
        drive_id = self.resolve_drive()
        remote_path = remote_path.strip("/")
        resp = self._request("GET", f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_path}")
        if resp.status_code != 200:
            raise SharePointWriteError(f"Nie znaleziono '{remote_path}': {resp.status_code} {resp.text[:300]}")
        return resp.json()

    def web_url(self, remote_path):
        """Link do folderu/pliku do wklejenia w komentarz Projectly."""
        return self.get_item(remote_path).get("webUrl", "")

    def list_children(self, remote_path=""):
        """ODCZYT: nazwy + typ (folder/plik) + webUrl elementów w folderze —
        'sprawdź co jest w tym folderze SharePoint' (żądanie właściciela
        29.08.2026: agenci/subagenci mają mieć odczyt do innych witryn firmy)."""
        resp = self._request("GET", self._children_url(remote_path))
        if resp.status_code != 200:
            raise SharePointWriteError(f"Nie udało się wypisać '{remote_path or '/'}': "
                                       f"{resp.status_code} {resp.text[:300]}")
        return [
            {"name": item.get("name"), "is_folder": "folder" in item, "web_url": item.get("webUrl", "")}
            for item in resp.json().get("value", [])
        ]

    def read_text(self, remote_path):
        """ODCZYT treści pliku jako tekst (UTF-8) — dla dokumentów tekstowych
        (.md/.txt/.csv/.json). Pliki binarne (.docx/.pdf/.xlsx) zgłaszają się
        czytelnym błędem zamiast zwracać nieczytelne bajty — czytanie ich
        treści wymaga innej biblioteki (poza zakresem tej funkcji, patrz
        document_builder.py/ocr_extract.py dla wzorców parsowania formatów)."""
        drive_id = self.resolve_drive()
        remote_path = remote_path.strip("/")
        resp = self._request("GET", f"{GRAPH_BASE}/drives/{drive_id}/root:/{remote_path}:/content")
        if resp.status_code != 200:
            raise SharePointWriteError(f"Nie udało się odczytać '{remote_path}': "
                                       f"{resp.status_code} {resp.text[:300]}")
        try:
            return resp.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SharePointWriteError(
                f"'{remote_path}' nie jest plikiem tekstowym (UTF-8) — read_text nie obsługuje "
                f"formatów binarnych (docx/pdf/xlsx)."
            ) from exc


def get_sharepoint_client():
    """Realny klient, gdy sekrety MS_GRAPH_* i msal są dostępne — inaczej None
    (fail-closed: wołający decyduje, co robić bez realnego dostępu, tak jak
    email_client.get_email_client() robi to dla poczty). Zapis (upload_file) —
    ZAWSZE ta jedna witryna z config/sharepoint.yaml (site_host/site_path)."""
    import os

    required = ["MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID"]
    if any(not os.environ.get(k) for k in required) or not msal_available():
        return None

    import yaml
    from pathlib import Path

    config_path = Path(__file__).parent / "config" / "sharepoint.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return SharePointClient(
        os.environ["MS_GRAPH_CLIENT_ID"], os.environ["MS_GRAPH_CLIENT_SECRET"], os.environ["MS_GRAPH_TENANT_ID"],
        config["site_host"], config["site_path"], library=config.get("library"),
    )


def get_sharepoint_client_for_site(site_host, site_path, library=None):
    """Jak get_sharepoint_client(), ale dla DOWOLNEJ witryny tej samej
    organizacji (site_host/site_path parametryzowane) — te same poświadczenia
    aplikacji (Graph app registration jest per-tenant, nie per-witryna), ale
    działa TYLKO jeśli aplikacja ma nadane uprawnienie odczytu tej konkretnej
    witryny (Sites.Read.All albo Sites.Selected + jawny dostęp) w Azure AD —
    to nadaje administrator, nie ten kod (patrz sharepoint_reader.py i
    config/sharepoint.yaml -> read_access). Do ODCZYTU (sharepoint_reader.py) —
    NIE do zapisu; wołający nie powinien wołać upload_file/ensure_folder na
    kliencie z tej fabryki."""
    import os

    required = ["MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID"]
    if any(not os.environ.get(k) for k in required) or not msal_available():
        return None
    return SharePointClient(
        os.environ["MS_GRAPH_CLIENT_ID"], os.environ["MS_GRAPH_CLIENT_SECRET"], os.environ["MS_GRAPH_TENANT_ID"],
        site_host, site_path, library=library,
    )
