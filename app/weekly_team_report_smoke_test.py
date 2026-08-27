"""
Test dymny weekly_team_report.py.

Żywy bug 23.08.2026: ai_weaknesses_summary() wołał client.messages.create()
(Anthropic SDK) bez obsługi błędu API (np. "credit balance too low") — sam
błąd wywalał WYJĄTKIEM całą funkcję run_weekly_team_report(), więc raport
tygodniowy nigdy nie docierał do Projectly ani na maila, mimo że surowe dane
(zadania, wpisy czasu) były już gotowe. Naprawa: błąd API degraduje do
raportu bez interpretacji AI (sekcja z powodem), raport i tak zostaje
opublikowany/wysłany.

Bez sieci: klient Projectly i klient mailowy są atrapami, klient Anthropic
(gdy testowany) jest podmieniony na atrapę rzucającą wyjątek SDK.
"""

from datetime import date

import weekly_team_report
from weekly_team_report import ai_weaknesses_summary, build_team_report, run_weekly_team_report


class _FakeProjectlyClient:
    def __init__(self, tasks=None):
        self._tasks = tasks or []
        self.comments = []

    def list_tasks(self):
        return self._tasks

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True


class _FakeMailClient:
    def __init__(self):
        self.sent = []

    def send_email(self, to, subject, body_text, cc=None):
        self.sent.append((to, subject, body_text))
        return "mock-path"


class _FakeAnthropicClientRaising:
    """Atrapa klienta Anthropic — messages.create() rzuca wyjątek SDK, tak
    jak realne API przy np. 'credit balance too low'."""

    class _Messages:
        def create(self, **kwargs):
            import anthropic
            raise anthropic.AnthropicError("credit balance too low")

    def __init__(self):
        self.messages = self._Messages()


SAMPLE_TASKS = [
    {"title": "Zamknięte zadanie", "status": "done", "assignee": "kacper"},
    {"title": "Stare zadanie", "status": "todo", "dueDate": "2026-08-01", "assignee": "pawel"},
]


def test_build_team_report_shows_ai_summary_when_present():
    split = {"done": [], "overdue": []}
    text = build_team_report(split, {}, ai_summary="Obserwacja testowa.")
    assert "Obserwacja testowa." in text
    assert "niedostępna" not in text
    print("OK  build_team_report wstawia sekcję z interpretacją AI, gdy jest dostępna")


def test_build_team_report_degrades_on_ai_error_without_crashing():
    split = {"done": [], "overdue": []}
    text = build_team_report(split, {}, ai_summary=None, ai_error="credit balance too low")
    assert "Analiza AI niedostępna: credit balance too low" in text
    assert "raport zawiera tylko surowe liczby powyżej" in text
    print("OK  build_team_report degraduje do raportu bez interpretacji AI, gdy był błąd API")


def test_build_team_report_no_key_message_unchanged_when_no_error():
    split = {"done": [], "overdue": []}
    text = build_team_report(split, {}, ai_summary=None, ai_error=None)
    assert "Brak ANTHROPIC_API_KEY" in text
    print("OK  brak klucza (bez błędu) nadal pokazuje pierwotny komunikat")


def test_ai_weaknesses_summary_returns_none_none_without_key(monkeypatch=None):
    import os
    original = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        summary, error = ai_weaknesses_summary({"overdue": []}, {})
    finally:
        if original is not None:
            os.environ["ANTHROPIC_API_KEY"] = original
    assert summary is None and error is None, "bez klucza nie wolno zwracać ani obserwacji, ani błędu"
    print("OK  bez ANTHROPIC_API_KEY: (None, None), bez wyjątku")


def test_ai_weaknesses_summary_catches_api_error_and_returns_reason():
    import os
    import anthropic

    original_key = os.environ.get("ANTHROPIC_API_KEY")
    original_anthropic_cls = anthropic.Anthropic
    os.environ["ANTHROPIC_API_KEY"] = "fake-key-do-testu"
    anthropic.Anthropic = lambda: _FakeAnthropicClientRaising()
    try:
        summary, error = ai_weaknesses_summary(
            {"overdue": [{"title": "Zadanie X"}]}, {"kacper": {"total_hours": 5.0}}
        )
    finally:
        anthropic.Anthropic = original_anthropic_cls
        if original_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = original_key

    assert summary is None, "błąd API nie może zostać podany jako obserwacja"
    assert error and "credit balance too low" in error
    print("OK  błąd API (Anthropic SDK) złapany, zwrócony jako powód degradacji, bez wyjątku")


def test_run_weekly_team_report_succeeds_and_publishes_despite_ai_api_error():
    """Regresja żywego bugu: mimo błędu API Anthropic cały raport MUSI
    dotrzeć do Projectly (post_comment) i na maila (send_email)."""
    import os
    import anthropic

    original_key = os.environ.get("ANTHROPIC_API_KEY")
    original_anthropic_cls = anthropic.Anthropic
    original_get_email_client = weekly_team_report.get_email_client
    os.environ["ANTHROPIC_API_KEY"] = "fake-key-do-testu"
    anthropic.Anthropic = lambda: _FakeAnthropicClientRaising()
    fake_mail = _FakeMailClient()
    weekly_team_report.get_email_client = lambda: fake_mail
    projectly = _FakeProjectlyClient(tasks=SAMPLE_TASKS)
    try:
        text = run_weekly_team_report(client=projectly, today=date(2026, 8, 24))
    finally:
        anthropic.Anthropic = original_anthropic_cls
        weekly_team_report.get_email_client = original_get_email_client
        if original_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = original_key

    assert text, "raport tekstowy musi powstać mimo błędu API"
    assert "Analiza AI niedostępna" in text, "raport ma jawnie informować o degradacji, nie milczeć"
    assert len(projectly.comments) == 1, "raport MUSI dotrzeć do Projectly (post_comment), mimo błędu AI"
    assert projectly.comments[0][0] == "WEEKLY-TEAM-REPORT"
    assert projectly.comments[0][1] == text
    assert len(fake_mail.sent) == 1, "raport MUSI dotrzeć mailem, mimo błędu AI"
    assert fake_mail.sent[0][2] == text
    print("OK  run_weekly_team_report konczy sie sukcesem i publikuje raport mimo bledu API Anthropic")


if __name__ == "__main__":
    test_build_team_report_shows_ai_summary_when_present()
    test_build_team_report_degrades_on_ai_error_without_crashing()
    test_build_team_report_no_key_message_unchanged_when_no_error()
    test_ai_weaknesses_summary_returns_none_none_without_key()
    test_ai_weaknesses_summary_catches_api_error_and_returns_reason()
    test_run_weekly_team_report_succeeds_and_publishes_despite_ai_api_error()
    print("\nWszystkie testy weekly_team_report przeszły.")
