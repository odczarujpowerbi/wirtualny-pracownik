"""
Test dymny mailerlite_report_analyzer.py (brak dedykowanego testu — potwierdzone
w audycie 27.08.2026, jedno realne uruchomienie tego joba w historii skończyło
się błędem API Anthropic).

Żywy bug: ai_feedback() wołał client.messages.create() (Anthropic SDK) bez
obsługi błędu API (np. "insufficient credit balance") — błąd wywalałby
WYJĄTKIEM run_weekly_report() dla WSZYSTKICH kampanii w raporcie, mimo że
statystyki i heurystyka czytelności (czysty Python, bez modelu) były już
policzone. Naprawa, analogiczna do weekly_team_report.py: samo wywołanie
modelu jest owinięte w try/except (anthropic.AnthropicError) — błąd degraduje
TYLKO ocenę treści/tytułu tej jednej kampanii do jasnej adnotacji, raport i
tak zostaje zbudowany i opublikowany.

Pokrywa też wcześniej naprawiony bug: build_report() czyta c["temat"]
(kształt znormalizowany przez mailerlite_client.normalizuj_kampanie(), NIE
surowy klucz "subject" z API) — kampania bez pola "subject" w danych z API
nie może rzucić KeyError, bo normalizuj_kampanie() ma fallback na "name".

Bez sieci: klient Projectly i klient MailerLite są atrapami, klient Anthropic
(gdy testowany) jest podmieniony na atrapę zwracającą tekst albo rzucającą
wyjątek SDK.
"""

import os

import anthropic

import mailerlite_client
from mailerlite_report_analyzer import ai_feedback, build_report, run_weekly_report

CAMPAIGN_COMPLETE = {
    "id": "1",
    "nazwa": "Newsletter sierpień",
    "temat": "Nowości w produkcie",
    "tresc_plain": "To jest krótka i klarowna wiadomość. Ma dwa zdania.",
    "data_wysylki": None,
    "odbiorcy": 1000,
    "otwarcia": 400,
    "klikniecia": 50,
    "rezygnacje": 2,
    "odbicia": 1,
    "open_rate": 40.0,
    "ctr": 5.0,
    "surowe_stats_klucze": ["opens", "clicks"],
}


class _FakeContentBlock:
    def __init__(self, text):
        self.text = text


class _FakeMessage:
    def __init__(self, text):
        self.content = [_FakeContentBlock(text)]


class _FakeAnthropicClientSuccess:
    """Atrapa klienta Anthropic — messages.create() zwraca tekst oceny."""

    class _Messages:
        def __init__(self, text):
            self._text = text

        def create(self, **kwargs):
            return _FakeMessage(self._text)

    def __init__(self, text="Tytuł zachęca do otwarcia, treść klarowna. Popraw CTA na końcu."):
        self.messages = self._Messages(text)


class _FakeAnthropicClientRaising:
    """Atrapa klienta Anthropic — messages.create() rzuca wyjątek SDK, tak
    jak realne API przy np. 'insufficient credit balance'."""

    class _Messages:
        def create(self, **kwargs):
            raise anthropic.AnthropicError("insufficient credit balance")

    def __init__(self):
        self.messages = self._Messages()


class _FakeProjectlyClient:
    def __init__(self):
        self.comments = []

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True


class _FakeMailerLiteClient:
    def __init__(self, campaigns):
        self._campaigns = campaigns

    def get_campaigns_sent_since(self, since_iso_date):
        return self._campaigns


def _z_kluczem_api(anthropic_client_factory):
    """Ustawia ANTHROPIC_API_KEY i podmienia anthropic.Anthropic na atrapę.
    Zwraca funkcję przywracającą oryginalny stan (do finally)."""
    original_key = os.environ.get("ANTHROPIC_API_KEY")
    original_anthropic_cls = anthropic.Anthropic
    os.environ["ANTHROPIC_API_KEY"] = "fake-key-do-testu"
    anthropic.Anthropic = anthropic_client_factory

    def _przywroc():
        anthropic.Anthropic = original_anthropic_cls
        if original_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = original_key

    return _przywroc


def test_build_report_happy_path_complete_campaign():
    """Kampania z kompletnymi danymi (statystyki + treść) buduje pełną sekcję
    raportu, bez klucza API sekcja oceny AI jest jasnym stubem, nie wyjątkiem."""
    original_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        text = build_report([CAMPAIGN_COMPLETE])
    finally:
        if original_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = original_key

    assert "### Nowości w produkcie" in text
    assert "open rate 40.0%" in text
    assert "CTR 5.0%" in text
    assert "click-to-open 12.5%" in text
    assert "Brak ANTHROPIC_API_KEY" in text, "bez klucza sekcja AI ma być jasnym stubem"
    print("OK  build_report: kampania z kompletnymi danymi renderuje pełną sekcję")


def test_normalizuj_kampanie_missing_subject_falls_back_to_name_no_keyerror():
    """Kampania z API bez pola 'subject' (surowy klucz) — normalizuj_kampanie()
    ma fallback na 'name', więc c['temat'] w build_report() nigdy nie dostaje
    brakującego klucza (żywy bug w historii, już naprawiony w kodzie)."""
    surowa = {
        "id": "2",
        "name": "Kampania bez tematu",
        "emails": [{"plain_text": "Krótka treść bez tematu w danych API."}],
        "stats": {"sent": 10, "unique_opens_count": 2, "unique_clicks_count": 1},
    }
    znormalizowana = mailerlite_client.normalizuj_kampanie(surowa)
    assert znormalizowana["temat"] == "Kampania bez tematu", "brak 'subject' -> fallback na 'name'"

    text = build_report([znormalizowana])
    assert "### Kampania bez tematu" in text, "raport musi powstać bez KeyError na brakującym 'subject'"
    print("OK  brak pola 'subject' w danych API: fallback na 'name', build_report bez KeyError")


def test_ai_feedback_missing_api_key_returns_stub_not_exception():
    original_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        wynik = ai_feedback("Temat testowy", "Treść testowa.")
    finally:
        if original_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = original_key

    assert "Brak ANTHROPIC_API_KEY" in wynik
    print("OK  ai_feedback bez klucza: jasny stub, bez wyjątku")


def test_ai_feedback_success_returns_model_text():
    przywroc = _z_kluczem_api(lambda: _FakeAnthropicClientSuccess("Świetny tytuł, treść klarowna."))
    try:
        wynik = ai_feedback("Temat testowy", "Treść testowa.")
    finally:
        przywroc()

    assert wynik == "Świetny tytuł, treść klarowna."
    print("OK  ai_feedback happy path: zwraca ocenę modelu")


def test_ai_feedback_api_error_degrades_without_crashing():
    """Błąd API modelu (np. brak środków na koncie) nie może wywalić
    ai_feedback() wyjątkiem — ma zwrócić jasną adnotację degradacji."""
    przywroc = _z_kluczem_api(lambda: _FakeAnthropicClientRaising())
    try:
        wynik = ai_feedback("Temat testowy", "Treść testowa.")
    finally:
        przywroc()

    assert "niedostępna" in wynik
    assert "insufficient credit balance" in wynik
    print("OK  ai_feedback: błąd API Anthropic złapany, zwrócony jako adnotacja, bez wyjątku")


def test_run_weekly_report_succeeds_and_publishes_despite_ai_api_error():
    """Regresja żywego bugu: mimo błędu API Anthropic cały raport MUSI
    powstać i dotrzeć do Projectly (post_comment), nie tylko dla jednej,
    ale dla WSZYSTKICH kampanii w oknie tygodniowym."""
    przywroc = _z_kluczem_api(lambda: _FakeAnthropicClientRaising())
    projectly = _FakeProjectlyClient()
    mailerlite = _FakeMailerLiteClient([CAMPAIGN_COMPLETE, dict(CAMPAIGN_COMPLETE, id="2", temat="Druga kampania")])
    try:
        text = run_weekly_report(client=projectly, mailerlite_client=mailerlite)
    finally:
        przywroc()

    assert text, "raport tekstowy musi powstać mimo błędu API"
    assert text.count("Ocena AI niedostępna") == 2, "obie kampanie mają zdegradowaną sekcję AI, nie brakującą"
    assert len(projectly.comments) == 1, "raport MUSI dotrzeć do Projectly (post_comment), mimo błędu AI"
    assert projectly.comments[0][0] == "MAILERLITE-WEEKLY-REPORT"
    assert projectly.comments[0][1] == text
    print("OK  run_weekly_report kończy się sukcesem i publikuje raport mimo błędu API Anthropic")


if __name__ == "__main__":
    test_build_report_happy_path_complete_campaign()
    test_normalizuj_kampanie_missing_subject_falls_back_to_name_no_keyerror()
    test_ai_feedback_missing_api_key_returns_stub_not_exception()
    test_ai_feedback_success_returns_model_text()
    test_ai_feedback_api_error_degrades_without_crashing()
    test_run_weekly_report_succeeds_and_publishes_despite_ai_api_error()
    print("\nWszystkie testy mailerlite_report_analyzer przeszły.")
