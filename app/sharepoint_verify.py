"""
Weryfikacja dostepu Microsoft Graph do SharePoint (app-only, client credentials).
Odpowiada na pytanie: "czy sekrety MS_GRAPH_* faktycznie ladują token i czy
Graph wpuszcza do witryny/drive'a config/sharepoint.yaml?". NIE tworzy folderu,
NIE wgrywa pliku.

Dwa etapy:
  1. token - pobranie tokenu app-only (dowod poprawnych client_id/secret/tenant
             + admin consent). Ten sam token, co microsoft_graph_mail_client.py.
  2. site  - GET witryny + drive'a (dowod, ze Sites.Read.All/Files.Read.All
             dziala i witryna/biblioteka z sharepoint.yaml istnieje). 403 tutaj
             NIE jest bledem tokenu - token juz dowodzi, ze auth dziala, ale
             brakuje uprawnienia aplikacyjnego Sites.ReadWrite.All/Files.ReadWrite.All
             z admin consent (do nadania w Azure AD, poza zasiegiem tego skryptu).

Nigdy nie loguje sekretow. Uzycie: python sharepoint_verify.py
"""

import os

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env
import sharepoint_client as sp

_REQUIRED = ["MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID"]


def missing_env():
    return [k for k in _REQUIRED if not os.environ.get(k)]


def verify():
    """Zwraca {ok, stage, detail}. Nie rzuca - kazda porazke zwraca jako wynik."""
    missing = missing_env()
    if missing:
        return {"ok": False, "stage": "env", "detail": f"Brak w secrets/.env: {', '.join(missing)}"}
    if not sp.msal_available():
        return {"ok": False, "stage": "deps", "detail": "Brak pakietu 'msal' (pip install msal)."}

    client = sp.get_sharepoint_client()
    if client is None:
        return {"ok": False, "stage": "deps", "detail": "get_sharepoint_client() zwrocil None (sekrety/msal/config)."}

    try:
        client._acquire_token()
    except sp.SharePointAuthError as exc:
        return {"ok": False, "stage": "token", "detail": str(exc)}

    try:
        drive_id = client.resolve_drive()
    except sp.SharePointWriteError as exc:
        return {"ok": True, "stage": "token",
                "detail": f"Token OK (auth dziala). Odczyt witryny/drive'a nieudany: {exc}"}

    return {"ok": True, "stage": "site",
            "detail": f"Token OK + witryna/drive OK: drive_id={drive_id}, webUrl={client._drive_web_url}"}


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = verify()
    print(("OK   " if r["ok"] else "BLAD ") + f"[{r['stage']}] {r['detail']}")
    sys.exit(0 if r["ok"] else 1)
