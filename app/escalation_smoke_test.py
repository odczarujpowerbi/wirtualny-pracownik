"""
Test dymny escalation.py. Zero sieci — klient Projectly i klient mailowy to
atrapy; `email_client.get_email_client` podmieniony, żeby sprawdzić, że
escalate_to_human FAKTYCZNIE wysyła powiadomienie (decyzja właściciela
25.08.2026: to JEDYNE miejsce w pipeline, które ma prawo wysłać mail) i że
błąd wysyłki nie blokuje eskalacji.

Użycie:
    python escalation_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import escalation
import state_store

TASK = {"task_id": "T-ESK-1", "title": "Zadanie testowe", "project_id": "PROJ-1"}


class _FakeProjectlyClient:
    def __init__(self):
        self.utworzone = []

    def create_task(self, title, description, assigned_to, parent_task_id=None,
                    project_id=None, relation_type="eskalacja"):
        self.utworzone.append({"title": title, "description": description, "assigned_to": assigned_to,
                              "parent_task_id": parent_task_id, "project_id": project_id,
                              "relation_type": relation_type})
        return f"ESK-{len(self.utworzone)}"


class _FakeEmailClient:
    def __init__(self, rzuca=False):
        self.wyslane = []
        self.rzuca = rzuca

    def send_email(self, to, subject, body_text, cc=None):
        if self.rzuca:
            raise RuntimeError("Symulowany błąd Graph.")
        self.wyslane.append({"to": to, "subject": subject, "body_text": body_text})
        return {"status": "ok"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_get_email_client = escalation.email_client.get_email_client
    original_db_path = state_store.DB_PATH

    try:
        state_store.DB_PATH = Path(tempfile.mkdtemp()) / "state.db"

        # --- 1. Happy path: zadanie eskalacji powstaje + mail wysłany ---
        fake_mail = _FakeEmailClient()
        escalation.email_client.get_email_client = lambda: fake_mail
        projectly = _FakeProjectlyClient()

        new_id = escalation.escalate_to_human(TASK, "Brak dostępu do API.", projectly, assignee="pawel")
        checks.append(("escalate_to_human: zadanie utworzone w Projectly", len(projectly.utworzone) == 1))
        checks.append(("escalate_to_human: tytuł 'Wymaga decyzji: ...'",
                       projectly.utworzone[0]["title"] == "Wymaga decyzji: Zadanie testowe"))
        checks.append(("escalate_to_human: relation_type='eskalacja'",
                       projectly.utworzone[0]["relation_type"] == "eskalacja"))
        checks.append(("escalate_to_human: zwraca id nowego zadania", new_id == "ESK-1"))
        checks.append(("escalate_to_human: mail FAKTYCZNIE wysłany", len(fake_mail.wyslane) == 1))
        checks.append(("escalate_to_human: temat maila wspomina zadanie",
                       "Zadanie testowe" in fake_mail.wyslane[0]["subject"]))
        checks.append(("escalate_to_human: treść maila niesie powód i id zadania eskalacji",
                       "Brak dostępu do API." in fake_mail.wyslane[0]["body_text"]
                       and "ESK-1" in fake_mail.wyslane[0]["body_text"]))

        # --- 2. event escalated_to_human zapisany w dzienniku ---
        conn = state_store.get_connection()
        row = conn.execute(
            "SELECT detail FROM events WHERE task_id=? AND event_type='escalated_to_human' ORDER BY id DESC LIMIT 1",
            (TASK["task_id"],),
        ).fetchone()
        conn.close()
        checks.append(("escalate_to_human: zdarzenie 'escalated_to_human' zapisane", row is not None))

        # --- 3. Fail-soft: błąd wysyłki maila NIE blokuje eskalacji ---
        fake_mail_zly = _FakeEmailClient(rzuca=True)
        escalation.email_client.get_email_client = lambda: fake_mail_zly
        projectly2 = _FakeProjectlyClient()
        new_id2 = escalation.escalate_to_human(TASK, "Inny powód.", projectly2, assignee="pawel")
        checks.append(("Fail-soft: zadanie eskalacji i tak powstaje, gdy mail padnie",
                       len(projectly2.utworzone) == 1 and new_id2 == "ESK-1"))

        # --- 4. human_response_validator: podstawowe ścieżki ---
        checks.append(("human_response_validator: pusty komentarz -> niewystarczający",
                       escalation.human_response_validator("")["sufficient"] is False))
        checks.append(("human_response_validator: 'Zatwierdzam' -> jednoznaczna decyzja",
                       escalation.human_response_validator("Zatwierdzam, proszę kontynuować.")["sufficient"] is True))
        checks.append(("human_response_validator: dopytanie bez decyzji -> niewystarczający",
                       escalation.human_response_validator("A o co dokładnie chodzi?")["sufficient"] is False))
    finally:
        escalation.email_client.get_email_client = original_get_email_client
        state_store.DB_PATH = original_db_path

    print("\n--- Wynik testu dymnego escalation ---")
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
