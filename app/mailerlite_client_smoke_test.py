"""
Test dymny konektora MailerLite. Zero sieci — `requests` podmieniony na atrapę
(mailerlite_client.py importuje go NA GÓRZE pliku, nie leniwie, więc patchujemy
atrybut modułu już związany, nie sys.modules). Sprawdza fail-closed (brak
klucza = wyjątek, nie ciche dane z mocka), normalizację pól (tolerancja na
warianty nazw, brak pomiaru = None nie 0) i stronicowanie/filtr dat.

Użycie:
    python mailerlite_client_smoke_test.py
"""

import sys
import types
from datetime import date

import mailerlite_client as ml


class _FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}

    def json(self):
        return self._body


def _install_fake_requests(pages_by_page=None, single=None):
    fake = types.ModuleType("requests")
    captured = {"calls": []}

    def _get(url, headers=None, params=None, timeout=None):
        captured["calls"].append({"url": url, "params": params})
        if single is not None:
            return single
        page = (params or {}).get("page", 1)
        return pages_by_page[page]

    fake.get = _get
    ml.requests = fake
    return captured


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. get_mailerlite_client: fail closed — brak klucza = wyjątek, NIE cichy Mock.
    import os
    original_key = os.environ.pop("MAILERLITE_API_KEY", None)
    try:
        try:
            ml.get_mailerlite_client()
            raised = False
        except ml.MailerLiteNiedostepny:
            raised = True
        checks.append(("get_mailerlite_client: brak klucza -> MailerLiteNiedostepny (fail-closed)", raised))

        checks.append(("get_mailerlite_client(mock=True): zwraca Mock na jawne żądanie",
                       type(ml.get_mailerlite_client(mock=True)).__name__ == "MockMailerLiteClient"))

        os.environ["MAILERLITE_MOCK"] = "1"
        checks.append(("get_mailerlite_client: MAILERLITE_MOCK=1 -> Mock",
                       type(ml.get_mailerlite_client()).__name__ == "MockMailerLiteClient"))
        os.environ.pop("MAILERLITE_MOCK", None)

        os.environ["MAILERLITE_API_KEY"] = "fake-key"
        checks.append(("get_mailerlite_client: klucz obecny -> MailerLiteClient realny",
                       type(ml.get_mailerlite_client()).__name__ == "MailerLiteClient"))
    finally:
        if original_key is not None:
            os.environ["MAILERLITE_API_KEY"] = original_key
        else:
            os.environ.pop("MAILERLITE_API_KEY", None)

    client = ml.MailerLiteClient("fake-key")

    # 2. _get: 401/429/inne kody -> MailerLiteNiedostepny z powodem po polsku.
    for kod, fragment in ((401, "401"), (429, "429"), (500, "500")):
        _install_fake_requests(single=_FakeResponse(kod))
        try:
            client._get("/campaigns")
            raised = False
            detail = ""
        except ml.MailerLiteNiedostepny as exc:
            raised = True
            detail = str(exc)
        checks.append((f"_get: kod {kod} -> MailerLiteNiedostepny", raised and fragment in detail))

    # 3. normalizuj_kampanie: tolerancja wariantów nazw, brak pomiaru = None (nie 0).
    surowa = {
        "id": "1", "name": "Newsletter", "finished_at": "2026-08-14 09:30:00",
        "emails": [{"subject": "Temat testowy"}],
        "stats": {"sent": 100, "unique_opens_count": 40, "unique_clicks_count": 5},
    }
    znormalizowana = ml.normalizuj_kampanie(surowa)
    checks.append(("normalizuj_kampanie: temat z emails[0]", znormalizowana["temat"] == "Temat testowy"))
    checks.append(("normalizuj_kampanie: data_wysylki sparsowana", znormalizowana["data_wysylki"] == date(2026, 8, 14)))
    checks.append(("normalizuj_kampanie: open_rate policzony (40/100=40.0)", znormalizowana["open_rate"] == 40.0))
    checks.append(("normalizuj_kampanie: brak pomiaru -> None, nie 0",
                   ml.normalizuj_kampanie({"id": "2", "stats": {}})["rezygnacje"] is None))

    # 4. get_sent_campaigns: filtr dat po stronie klienta; strona niepełna (< LIMIT_STRONY)
    # sygnalizuje koniec, więc druga strona NIE jest odpytywana (paginacja poprawna).
    strona1 = {"data": [
        {"id": "1", "finished_at": "2026-08-20 06:00:00", "stats": {}},
        {"id": "2", "finished_at": "2026-08-18 06:00:00", "stats": {}},
        {"id": "3", "finished_at": "2026-08-10 06:00:00", "stats": {}},
    ]}
    captured = _install_fake_requests(pages_by_page={1: _FakeResponse(200, strona1)})
    kampanie, sprawdzono = client.get_sent_campaigns(date(2026, 8, 15), date(2026, 8, 25))
    checks.append(("get_sent_campaigns: filtruje po dacie (2/3 w oknie)", len(kampanie) == 2))
    checks.append(("get_sent_campaigns: sprawdzono wszystkie kampanie ze strony", sprawdzono == 3))
    checks.append(("get_sent_campaigns: niepełna strona -> nie dopytuje kolejnej", len(captured["calls"]) == 1))
    checks.append(("get_sent_campaigns: filter[status]=sent w zapytaniu",
                   captured["calls"][0]["params"]["filter[status]"] == "sent"))
    checks.append(("get_sent_campaigns: NIE wysyła nieistniejącego filter[since]",
                   all("filter[since]" not in c["params"] for c in captured["calls"])))

    # 5. get_campaigns_sent_since: zgodność wsteczna, delegacja do get_sent_campaigns.
    _install_fake_requests(pages_by_page={1: _FakeResponse(200, strona1)})
    wynik = client.get_campaigns_sent_since("2026-08-15")
    checks.append(("get_campaigns_sent_since: zgodność wsteczna działa", len(wynik) >= 1))

    # 6. MockMailerLiteClient: dane oznaczone mock=True (worker ma je rozpoznać i odmówić).
    mock_client = ml.MockMailerLiteClient()
    mock_kampanie, _ = mock_client.get_sent_campaigns(date.min, date.today())
    checks.append(("MockMailerLiteClient: kampanie oznaczone mock=True",
                   all(k.get("mock") is True for k in mock_kampanie)))

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
