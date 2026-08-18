"""
Klient poczty (config/integrations.yaml wpis `microsoft_365`: mail
read+send z jednego wspólnego konta). To jest STUB — prawdziwy dostęp
(Microsoft Graph + rejestracja aplikacji w Azure AD, pakiet `msal`,
patrz app/README.md "Co jeszcze będzie potrzebne") nie jest jeszcze
podłączony w tej sesji. Przygotowane z wyprzedzeniem, żeby po dostarczeniu
dostępu wystarczyło dopisać `EmailClient`, bez zmiany reszty pipeline'u
(`email_draft_generator.py` i przyszły `email_intake_triage.py`).

`draft_email` jest już `yellow` w approval_policy.yaml — realna wysyłka
przechodzi normalną ścieżkę walidacji/auto-zatwierdzenia (sekcja 3 planu),
zanim cokolwiek pójdzie do klienta. Ten moduł sam z siebie niczego nie
wysyła bez świadomego wywołania `send_email`.

BEZPIECZEŃSTWO (na wyraźne życzenie): dopóki approval_policy nie mówi
inaczej, KAŻDA wysyłka (`send_email`) leci do człowieka wewnątrz firmy —
adresaci w `config/email_safety.yaml` — a nie bezpośrednio do zamierzonego
adresata. Zamierzony adresat jest jawnie opisany w temacie i treści.
`save_draft` tego NIE robi — draft w skrzynce bota i tak nikt nie widzi,
dopóki ktoś ręcznie go nie wyśle.
"""

import os
import re
from pathlib import Path

import yaml

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem MS_GRAPH_*

MOCK_OUTBOX_DIR = Path(__file__).parent / "runs" / "mock_outbox"
EMAIL_SAFETY_PATH = Path(__file__).parent / "config" / "email_safety.yaml"

# Konektor Microsoft Graph (microsoft_graph_mail_client.py) jest już
# zaimplementowany. Realny klient włącza się, gdy SĄ wszystkie sekrety MS_GRAPH_*
# ORAZ zainstalowany jest pakiet `msal` (patrz get_email_client). Ustaw na False,
# żeby awaryjnie wymusić tryb mock nawet z sekretami.
GRAPH_SEND_IMPLEMENTED = True


def load_review_recipients(path=EMAIL_SAFETY_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("review_recipients", [])


def resolve_send_recipients(intended_to, subject, body_text, path=EMAIL_SAFETY_PATH):
    """Przekierowuje KAŻDĄ wysyłkę do ludzi z email_safety.yaml, zamiast
    bezpośrednio do zamierzonego adresata (fail-closed — brak wpisów w
    configu oznacza, że nic nie ma prawa wyjść, nie że wraca do zgadywania
    oryginalnego adresata)."""
    reviewers = load_review_recipients(path)
    if not reviewers:
        raise RuntimeError(
            "config/email_safety.yaml nie ma żadnych review_recipients — "
            "fail-closed: wysyłka zablokowana, dopóki lista jest pusta."
        )
    redirected_subject = f"[DO PRZEKAZANIA -> {intended_to}] {subject}"
    redirected_body = (
        f"(Bot: mail przygotowany dla {intended_to}, wysłany tutaj do przeglądu przed przekazaniem dalej.)\n\n"
        f"{body_text}"
    )
    return ", ".join(reviewers), redirected_subject, redirected_body


class EmailClient:
    """Realna wysyłka przez Microsoft Graph (microsoft_graph_mail_client.py).
    Przed każdą wysyłką stosuje przekierowanie odbiorców z email_safety.yaml —
    mail nie leci do zamierzonego adresata, tylko do ludzi wewnątrz firmy do
    przeglądu (fail-closed). save_draft nie przekierowuje (szkic w skrzynce bota
    i tak nikt nie widzi, dopóki ręcznie go nie wyśle)."""

    def __init__(self, client_id=None, client_secret=None, tenant_id=None, mailbox=None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id
        self.mailbox = mailbox
        self._mailer = None

    def _get_mailer(self):
        from microsoft_graph_mail_client import GraphMailer
        if self._mailer is None:
            self._mailer = GraphMailer(self.client_id, self.client_secret, self.tenant_id, self.mailbox)
        return self._mailer

    def send_email(self, to, subject, body_text, cc=None):
        review_to, redirected_subject, redirected_body = resolve_send_recipients(to, subject, body_text)
        result = self._get_mailer().send(review_to, redirected_subject, redirected_body, cc)
        print(f"[Graph Email] wysłano do przeglądu ({review_to}), status {result['status']}")
        return result

    def save_draft(self, to, subject, body_text, cc=None):
        return self._get_mailer().draft(to, subject, body_text, cc)


class MockEmailClient:
    """Nie wysyła niczego naprawdę — zapisuje treść jako plik tekstowy w
    runs/mock_outbox/, żeby dało się przejrzeć draft przed podłączeniem
    prawdziwej skrzynki (ten sam wzorzec co MockProjectlyClient)."""

    def __init__(self, outbox_dir=MOCK_OUTBOX_DIR):
        self.outbox_dir = outbox_dir

    def send_email(self, to, subject, body_text, cc=None):
        review_to, redirected_subject, redirected_body = resolve_send_recipients(to, subject, body_text)
        return self._write(
            review_to, redirected_subject, redirected_body, cc, action="SEND (mock — nie wysłano naprawdę)"
        )

    def save_draft(self, to, subject, body_text, cc=None):
        return self._write(to, subject, body_text, cc, action="DRAFT")

    def _write(self, to, subject, body_text, cc, action):
        self.outbox_dir.mkdir(parents=True, exist_ok=True)
        safe_subject = re.sub(r"[^\w\-]+", "_", subject)[:60] or "bez_tematu"
        existing = list(self.outbox_dir.glob(f"{safe_subject}_*.txt"))
        path = self.outbox_dir / f"{safe_subject}_{len(existing) + 1}.txt"

        content = f"Do: {to}\nDW: {cc or '-'}\nTemat: {subject}\nAkcja: {action}\n\n{body_text}\n"
        path.write_text(content, encoding="utf-8")
        print(f"[MOCK Email] {action} -> {path.name}")
        return str(path)


def get_email_client():
    """Real klient (Microsoft Graph) tylko, gdy JEDNOCZEŚNIE: są wszystkie
    sekrety MS_GRAPH_*, konektor jest włączony (GRAPH_SEND_IMPLEMENTED), oraz
    zainstalowany jest pakiet `msal`. Cokolwiek z tego brakuje -> tryb mock,
    bez crasha (fail-closed, ten sam wzorzec co projectly_client.get_client)."""
    from microsoft_graph_mail_client import msal_available

    required = ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID", "MS_GRAPH_MAILBOX")
    have_creds = all(os.environ.get(k) for k in required)

    if have_creds and GRAPH_SEND_IMPLEMENTED and msal_available():
        return EmailClient(
            client_id=os.environ["MS_GRAPH_CLIENT_ID"],
            client_secret=os.environ["MS_GRAPH_CLIENT_SECRET"],
            tenant_id=os.environ["MS_GRAPH_TENANT_ID"],
            mailbox=os.environ["MS_GRAPH_MAILBOX"],
        )

    if have_creds and GRAPH_SEND_IMPLEMENTED and not msal_available():
        print(
            "[email_client] Są sekrety MS_GRAPH_*, ale pakiet 'msal' nie jest zainstalowany "
            "(pip install -r requirements.txt) — używam trybu mock. Nic nie wychodzi na zewnątrz."
        )
    return MockEmailClient()
