"""
Test dymny konektora MailerLite. Zero sieci — moduł `requests` podmieniony
na atrapę. Sprawdza LOGIKĘ stronicowania/filtrowania po dacie w
get_campaigns_sent_since (naprawione 2026-08-22 po 400 Bad Request na koncie
produkcyjnym — `filter[since]` nie istnieje w REST MailerLite), nie prawdziwe
wywołanie API.

Użycie:
    python mailerlite_client_smoke_test.py
"""

import sys
import types

import mailerlite_client as ml


def _page(campaigns, page, last_page):
    return {"data": campaigns, "meta": {"current_page": page, "last_page": last_page}}


def _install_fake_requests(pages_by_page):
    # mailerlite_client.py importuje `requests` NA GÓRZE pliku (nie leniwie jak
    # microsoft_graph_mail_client.py) — sys.modules["requests"] po fakcie nie
    # wystarczy, trzeba podmienić atrybut już związany w module ml.
    fake = types.ModuleType("requests")
    captured = {"calls": []}

    class _FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self._body

    def _get(url, headers=None, params=None, timeout=None):
        captured["calls"].append(params)
        page = params.get("page", 1)
        return _FakeResponse(pages_by_page[page])

    fake.get = _get
    ml.requests = fake
    return captured


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. filter[since] NIGDY nie jest wysyłane (to był bug — 400 Bad Request na produkcji).
    campaigns_p1 = [
        {"id": "3", "finished_at": "2026-08-20 06:00:00"},
        {"id": "2", "finished_at": "2026-08-18 06:00:00"},
        {"id": "1", "finished_at": "2026-08-10 06:00:00"},  # starsza niż since -> stop
    ]
    pages = {1: _page(campaigns_p1, 1, 2)}
    captured = _install_fake_requests(pages)
    client = ml.MailerLiteClient("fake-key")
    result = client.get_campaigns_sent_since("2026-08-15")
    checks.append(("get_campaigns_sent_since: NIE wysyła filter[since]",
                   all("filter[since]" not in (p or {}) for p in captured["calls"])))
    checks.append(("get_campaigns_sent_since: wysyła filter[status]=sent",
                   captured["calls"][0]["filter[status]"] == "sent"))
    checks.append(("get_campaigns_sent_since: zatrzymuje się na kampanii starszej niż since",
                   [c["id"] for c in result] == ["3", "2"]))

    # 2. Stronicowanie: druga strona doczytana, gdy pierwsza w całości >= since.
    campaigns_p1b = [{"id": "5", "finished_at": "2026-08-20 06:00:00"}]
    campaigns_p2b = [{"id": "4", "finished_at": "2026-08-16 06:00:00"},
                     {"id": "3", "finished_at": "2026-08-05 06:00:00"}]
    pages2 = {1: _page(campaigns_p1b, 1, 2), 2: _page(campaigns_p2b, 2, 2)}
    captured2 = _install_fake_requests(pages2)
    result2 = client.get_campaigns_sent_since("2026-08-15")
    checks.append(("get_campaigns_sent_since: doczytuje kolejną stronę", len(captured2["calls"]) == 2))
    checks.append(("get_campaigns_sent_since: wynik z 2 stron, zatrzymany na starszej",
                   [c["id"] for c in result2] == ["5", "4"]))

    # 3. Brak kampanii na stronie -> pusty wynik, bez błędu.
    pages3 = {1: _page([], 1, 1)}
    _install_fake_requests(pages3)
    result3 = client.get_campaigns_sent_since("2026-08-15")
    checks.append(("get_campaigns_sent_since: brak danych -> lista pusta", result3 == []))

    # 4. get_mailerlite_client: brak klucza -> Mock (fail-closed, nie crash).
    import os
    original = os.environ.pop("MAILERLITE_API_KEY", None)
    try:
        checks.append(("get_mailerlite_client: brak klucza -> Mock",
                       type(ml.get_mailerlite_client()).__name__ == "MockMailerLiteClient"))
    finally:
        if original is not None:
            os.environ["MAILERLITE_API_KEY"] = original

    print("\n--- Wynik testu dymnego konektora MailerLite ---")
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
