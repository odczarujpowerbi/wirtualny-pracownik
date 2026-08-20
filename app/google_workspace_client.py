"""
Konektor Google Workspace przez KONTO SERWISOWE (Service Account) - wzorzec
dla agenta serwerowego (bez klikania "zezwol"). Uwierzytelnianie: plik JSON z
kluczem konta serwisowego, sciezka w secrets/.env:

    GOOGLE_APPLICATION_CREDENTIALS=...\app\secrets\google_service_account.json

Opcjonalnie delegacja domenowa (impersonacja uzytkownika Workspace) przez
GOOGLE_DELEGATED_USER=user@firma.pl - potrzebna, gdy chcesz dzialac na Drive/
Sheets konkretnego czlowieka, a nie tylko na zasobach udostepnionych kontu
serwisowemu.

Zaleznosci: google-auth + google-api-python-client (leniwy import, zeby sam
import modulu ich nie wymagal). READ-ONLY na start (Drive metadata).
"""

import os

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env

CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
DELEGATED_USER_ENV = "GOOGLE_DELEGATED_USER"
DEFAULT_SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]


class GoogleAuthError(RuntimeError):
    """Brak/niepoprawny plik konta serwisowego albo brak bibliotek."""


class GoogleWorkspaceClient:
    def __init__(self, credentials_path, scopes=None, delegated_user=None):
        if not credentials_path or not os.path.isfile(credentials_path):
            raise GoogleAuthError(f"Plik konta serwisowego nie istnieje: {credentials_path}")
        self.credentials_path = credentials_path
        self.scopes = scopes or DEFAULT_SCOPES
        self.delegated_user = delegated_user
        self._creds = None

    @classmethod
    def from_env(cls, scopes=None):
        """Klient z secrets/.env albo None, gdy brak sciezki do klucza (nie rzuca)."""
        path = os.environ.get(CREDENTIALS_ENV)
        if not path:
            return None
        return cls(path, scopes=scopes, delegated_user=os.environ.get(DELEGATED_USER_ENV))

    def _credentials(self):
        if self._creds is not None:
            return self._creds
        try:
            from google.oauth2 import service_account
        except ImportError as exc:
            raise GoogleAuthError("Brak pakietu 'google-auth' (pip install google-auth).") from exc
        creds = service_account.Credentials.from_service_account_file(self.credentials_path, scopes=self.scopes)
        if self.delegated_user:
            creds = creds.with_subject(self.delegated_user)
        self._creds = creds
        return creds

    def _service(self, api, version):
        try:
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleAuthError("Brak pakietu 'google-api-python-client'.") from exc
        return build(api, version, credentials=self._credentials(), cache_discovery=False)

    def drive_list_files(self, page_size=10):
        """Lista plikow widocznych dla konta (dowod dzialajacej autoryzacji + API)."""
        service = self._service("drive", "v3")
        result = service.files().list(pageSize=page_size, fields="files(id,name,mimeType)").execute()
        return result.get("files", [])


def verify():
    """Zwraca {ok, detail}. Bez sciezki/pliku -> ok=False (nie rzuca)."""
    client = GoogleWorkspaceClient.from_env()
    if client is None:
        return {"ok": False, "detail": f"Brak {CREDENTIALS_ENV} w secrets/.env (sciezka do JSON konta serwisowego)."}
    try:
        files = client.drive_list_files(page_size=5)
        return {"ok": True, "detail": f"OK - autoryzacja konta serwisowego dziala, plikow widocznych (probka): {len(files)}"}
    except GoogleAuthError as exc:
        return {"ok": False, "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001 - blad API (np. Drive API wylaczone w projekcie)
        return {"ok": False, "detail": f"Autoryzacja moze byc ok, ale wywolanie API zawiodlo: {exc}"}


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = verify()
    print(("OK   " if r["ok"] else "BLAD ") + r["detail"])
    sys.exit(0 if r["ok"] else 1)
