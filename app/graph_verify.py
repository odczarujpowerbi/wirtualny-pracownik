"""
Weryfikacja dostepu Microsoft Graph (app-only, client credentials). Odpowiada na
pytanie z wdrozenia: "czy sekrety MS_GRAPH_* faktycznie laduja token i czy Graph
wpuszcza?". NIE wysyla maila.

Dwa etapy:
  1. token   - pobranie tokenu app-only (dowod poprawnych client_id/secret/tenant
               + admin consent). To rdzen odpowiedzi "czy sie dostaje".
  2. read    - proba odczytu skrzynki (dowod, ze mailbox istnieje i aplikacja ma
               do niej dostep). 403/404 przy samym Mail.Send to NIE blad konfiguracji
               tokenu - token juz dowodzi, ze auth dziala.

Nigdy nie loguje sekretow. Uzycie: python graph_verify.py
"""

import os

import env_bootstrap  # noqa: F401  # wczytuje secrets/.env
import microsoft_graph_mail_client as graph

_REQUIRED = ["MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID", "MS_GRAPH_MAILBOX"]


def missing_env():
    """Ktore z wymaganych zmiennych MS_GRAPH_* nie sa ustawione."""
    return [k for k in _REQUIRED if not os.environ.get(k)]


def verify():
    """Zwraca {ok, stage, detail}. Nie rzuca - kazda porazke zwraca jako wynik."""
    missing = missing_env()
    if missing:
        return {"ok": False, "stage": "env", "detail": f"Brak w secrets/.env: {', '.join(missing)}"}
    if not graph.msal_available():
        return {"ok": False, "stage": "deps", "detail": "Brak pakietu 'msal' (pip install msal)."}
    try:
        import requests
    except ImportError:
        return {"ok": False, "stage": "deps", "detail": "Brak pakietu 'requests' (pip install requests)."}

    mailer = graph.GraphMailer(
        os.environ["MS_GRAPH_CLIENT_ID"], os.environ["MS_GRAPH_CLIENT_SECRET"],
        os.environ["MS_GRAPH_TENANT_ID"], os.environ["MS_GRAPH_MAILBOX"],
    )
    try:
        token = mailer._acquire_token()
    except graph.GraphAuthError as exc:
        return {"ok": False, "stage": "token", "detail": str(exc)}

    mailbox = os.environ["MS_GRAPH_MAILBOX"]
    url = f"{graph.GRAPH_BASE}/users/{mailbox}?$select=displayName,mail,userPrincipalName"
    try:
        resp = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                            timeout=graph.HTTP_TIMEOUT_SECONDS)
    except Exception as exc:  # noqa: BLE001 - siec: token i tak juz dowiodl auth
        return {"ok": True, "stage": "token",
                "detail": f"Token OK (auth dziala). Odczyt skrzynki nieudany (siec): {exc}"}

    if resp.status_code == 200:
        d = resp.json()
        who = d.get("mail") or d.get("userPrincipalName") or mailbox
        return {"ok": True, "stage": "read",
                "detail": f"Token OK + odczyt skrzynki OK: {d.get('displayName')} <{who}>"}
    return {"ok": True, "stage": "token",
            "detail": (f"Token OK (auth dziala). Odczyt skrzynki zwrocil {resp.status_code} - "
                       "to normalne, jesli aplikacja ma tylko Mail.Send (bez User.Read.All).")}


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = verify()
    print(("OK   " if r["ok"] else "BLAD ") + f"[{r['stage']}] {r['detail']}")
    sys.exit(0 if r["ok"] else 1)
