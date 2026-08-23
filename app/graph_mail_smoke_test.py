"""
Test dymny konektora Microsoft Graph i wyboru klienta poczty. Nie wymaga msal,
requests ani sieci — token i warstwa HTTP są podmieniane na atrapy, więc test
sprawdza LOGIKĘ (format wiadomości, obsługę kodów odpowiedzi, przekierowanie
odbiorców z email_safety.yaml, wybór realny/mock), nie prawdziwą wysyłkę.

Użycie:
    python graph_mail_smoke_test.py
"""

import sys
import types

import email_client
import microsoft_graph_mail_client as graph


class _FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = str(body)
        self.content = b"x"

    def json(self):
        return self._body


def _install_fake_requests(captured):
    """Wstrzykuje atrapę modułu `requests`, żeby test działał bez instalacji
    i bez sieci. Zapisuje ostatnie wywołanie do `captured`."""
    fake = types.ModuleType("requests")

    def _post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return captured["response"]

    fake.post = _post
    sys.modules["requests"] = fake


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. build_message: poprawny format Graph, odbiorcy z listy/stringa.
    msg = graph.build_message("a@x.pl, b@x.pl", "Temat", "Treść", cc="c@x.pl")
    checks.append(("build_message: 2 toRecipients + 1 cc + Text body",
                   len(msg["toRecipients"]) == 2 and len(msg["ccRecipients"]) == 1
                   and msg["body"]["contentType"] == "Text"))

    # 2. GraphMailer.send: 202 -> sukces, właściwy URL i nagłówek Authorization.
    captured = {"response": _FakeResponse(202)}
    _install_fake_requests(captured)
    mailer = graph.GraphMailer("cid", "secret", "tenant", "bot@firma.pl")
    mailer._acquire_token = lambda: "FAKE_TOKEN"  # omijamy msal
    result = mailer.send("odbiorca@x.pl", "T", "B")
    checks.append(("GraphMailer.send: 202 -> status ok", result["status"] == 202))
    checks.append(("GraphMailer.send: URL to /users/<mailbox>/sendMail",
                   captured["url"].endswith("/users/bot@firma.pl/sendMail")))
    checks.append(("GraphMailer.send: nagłówek Bearer z tokenem",
                   captured["headers"]["Authorization"] == "Bearer FAKE_TOKEN"))

    # 2b. parse_mailbox_address: "Nazwa <adres>" (format z secrets/.env
    # znaleziony 24.08.2026, powodował 404 ErrorInvalidUser) -> czysty adres.
    checks.append(("parse_mailbox_address: wyciąga adres z 'Nazwa <adres>'",
                   graph.parse_mailbox_address("Clickless <kontakt@clickless.pl>") == "kontakt@clickless.pl"))
    checks.append(("parse_mailbox_address: czysty adres bez zmian",
                   graph.parse_mailbox_address("kontakt@clickless.pl") == "kontakt@clickless.pl"))
    mailer_display_name = graph.GraphMailer("cid", "secret", "tenant", "Clickless <kontakt@clickless.pl>")
    checks.append(("GraphMailer: normalizuje mailbox z 'Nazwa <adres>' już w __init__",
                   mailer_display_name.mailbox == "kontakt@clickless.pl"))

    # 3. GraphMailer.send: kod błędu -> GraphSendError.
    captured["response"] = _FakeResponse(500, {"error": "boom"})
    try:
        mailer.send("odbiorca@x.pl", "T", "B")
        raised = False
    except graph.GraphSendError:
        raised = True
    checks.append(("GraphMailer.send: 500 -> GraphSendError", raised))

    # 4. draft: 201 -> zwraca id.
    captured["response"] = _FakeResponse(201, {"id": "AAMk123"})
    draft = mailer.draft("odbiorca@x.pl", "T", "B")
    checks.append(("GraphMailer.draft: 201 -> zwraca id", draft["id"] == "AAMk123"))

    # 5. EmailClient.send_email: stosuje przekierowanie z email_safety.yaml.
    captured["response"] = _FakeResponse(202)
    ec = email_client.EmailClient("cid", "secret", "tenant", "bot@firma.pl")
    ec._mailer = mailer  # wstrzykujemy atrapowany mailer
    ec.send_email(to="klient@zewnetrzny.pl", subject="Oferta", body_text="treść")
    # odbiorca faktycznej wysyłki NIE może być klientem zewnętrznym (przekierowanie)
    sent_to = captured["json"]["message"]["toRecipients"][0]["emailAddress"]["address"]
    subject_sent = captured["json"]["message"]["subject"]
    checks.append(("EmailClient.send_email: NIE wysyła do adresata zewnętrznego",
                   sent_to != "klient@zewnetrzny.pl"))
    checks.append(("EmailClient.send_email: temat oznaczony DO PRZEKAZANIA",
                   "DO PRZEKAZANIA" in subject_sent and "klient@zewnetrzny.pl" in subject_sent))

    # 6. get_email_client: brak msal -> MockEmailClient (nie crash), mimo sekretów.
    import os
    for k in ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID", "MS_GRAPH_MAILBOX"):
        os.environ[k] = "x"
    original_msal_available = graph.msal_available
    try:
        graph.msal_available = lambda: False
        client_no_msal = email_client.get_email_client()
        checks.append(("get_email_client: sekrety + brak msal -> Mock (fail-closed)",
                       type(client_no_msal).__name__ == "MockEmailClient"))

        graph.msal_available = lambda: True
        client_real = email_client.get_email_client()
        checks.append(("get_email_client: sekrety + msal + flaga -> EmailClient (realny)",
                       type(client_real).__name__ == "EmailClient"))
    finally:
        graph.msal_available = original_msal_available
        for k in ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID", "MS_GRAPH_MAILBOX"):
            os.environ.pop(k, None)

    print("\n--- Wynik testu dymnego konektora Graph ---")
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
