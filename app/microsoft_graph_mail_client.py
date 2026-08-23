"""
Konektor Microsoft Graph do wysyłki i szkiców maili (integrations.yaml wpis
`microsoft_365`). Realizuje przepływ app-only (client credentials): aplikacja
zarejestrowana w Azure AD (Microsoft Entra) z uprawnieniem aplikacyjnym
`Mail.Send` uwierzytelnia się sekretem klienta i wysyła w imieniu skrzynki.

Wymagania (poza kodem):
- rejestracja aplikacji w Azure AD -> client_id, client_secret, tenant_id,
- uprawnienie APLIKACYJNE Mail.Send (z admin consent),
- skrzynka nadawcza (mailbox, np. adres konta bota).

Zależności: `msal` (token) + `requests` (REST Graph) — obie deklarowane w
requirements.txt. Import obu jest LENIWY (wewnątrz metod), żeby sam import tego
modułu nie wymagał ich obecności (email_client sprawdza dostępność wcześniej).

BEZPIECZEŃSTWO: ten moduł sam z siebie NIE stosuje przekierowania odbiorców z
email_safety.yaml — robi to warstwa wyżej (email_client.EmailClient), tak żeby
niżej trafiał już bezpieczny odbiorca. Ten moduł to czysta hydraulika Graph.
"""

import re

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
AUTHORITY_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}"
SCOPE = ["https://graph.microsoft.com/.default"]
HTTP_TIMEOUT_SECONDS = 30


class GraphAuthError(RuntimeError):
    """Nie udało się uzyskać tokenu (zła konfiguracja aplikacji/uprawnień)."""


class GraphSendError(RuntimeError):
    """Graph odrzucił wysyłkę/utworzenie szkicu (kod != 2xx)."""


def msal_available():
    try:
        import msal  # noqa: F401
        return True
    except ImportError:
        return False


def parse_mailbox_address(value):
    """MS_GRAPH_MAILBOX bywa wpisany po ludzku jako "Nazwa <adres@domena>"
    (znaleziono tak w secrets/.env 24.08.2026: "Clickless <kontakt@clickless.pl>"),
    ale Graph pod /users/{id} wymaga czystego adresu/UPN — z tym zapisem
    dostawał nieistniejącego użytkownika i odpowiadał 404 ErrorInvalidUser.
    Wyciąga adres z <...>, jeśli jest; inaczej zwraca wartość bez zmian
    (już czysty adres)."""
    if not value:
        return value
    match = re.search(r"<([^<>]+)>", value)
    return match.group(1).strip() if match else value.strip()


def _to_recipients(addresses):
    """Lista adresów (str z przecinkami albo lista) -> format Graph."""
    if isinstance(addresses, str):
        addresses = addresses.split(",")
    return [{"emailAddress": {"address": a.strip()}} for a in addresses if a and a.strip()]


def build_message(to, subject, body_text, cc=None):
    """Ładunek wiadomości w formacie Graph (współdzielony przez send i draft)."""
    message = {
        "subject": subject,
        "body": {"contentType": "Text", "content": body_text},
        "toRecipients": _to_recipients(to),
    }
    if cc:
        message["ccRecipients"] = _to_recipients(cc)
    return message


class GraphMailer:
    """Trzyma dane dostępowe i (leniwie) aplikację MSAL. Token jest cache'owany
    wewnątrz MSAL między wywołaniami, więc kolejne wysyłki nie logują się od nowa."""

    def __init__(self, client_id, client_secret, tenant_id, mailbox):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.mailbox = parse_mailbox_address(mailbox)
        self._app = None

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
            raise GraphAuthError(
                f"Nie uzyskano tokenu Graph: {result.get('error')} — "
                f"{(result.get('error_description') or '')[:200]}"
            )
        return result["access_token"]

    def _post(self, path, payload):
        import requests
        token = self._acquire_token()
        url = f"{GRAPH_BASE}/users/{self.mailbox}{path}"
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=HTTP_TIMEOUT_SECONDS,
        )
        return response

    def send(self, to, subject, body_text, cc=None):
        payload = {"message": build_message(to, subject, body_text, cc), "saveToSentItems": True}
        response = self._post("/sendMail", payload)
        if response.status_code not in (200, 202):
            raise GraphSendError(f"Graph sendMail zwrócił {response.status_code}: {response.text[:300]}")
        return {"status": response.status_code, "to": to}

    def draft(self, to, subject, body_text, cc=None):
        payload = build_message(to, subject, body_text, cc)
        response = self._post("/messages", payload)
        if response.status_code not in (200, 201):
            raise GraphSendError(f"Graph createDraft zwrócił {response.status_code}: {response.text[:300]}")
        data = response.json() if response.content else {}
        return {"status": response.status_code, "id": data.get("id")}
