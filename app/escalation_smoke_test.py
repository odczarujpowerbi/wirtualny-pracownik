"""
Test dymny escalation.py. Zero sieci — klient Projectly i klient mailowy to
atrapy; `email_client.get_email_client` podmieniony, żeby sprawdzić, że
escalate_to_human FAKTYCZNIE wysyła powiadomienie (decyzja właściciela
25.08.2026: to JEDYNE miejsce w pipeline, które ma prawo wysłać mail) i że
błąd wysyłki nie blokuje eskalacji.

Użycie:
    python escalation_smoke_test.py
"""

import contextlib
import io
import sys
import tempfile
from pathlib import Path

import escalation
import projectly_client
import state_store

TASK = {"task_id": "T-ESK-1", "title": "Zadanie testowe", "project_id": "PROJ-1"}


class _FakeProjectlyClient:
    def __init__(self):
        self.utworzone = []

    def create_task(self, title, description, assigned_to, parent_task_id=None,
                    project_id=None, relation_type="eskalacja", priority=None):
        self.utworzone.append({"title": title, "description": description, "assigned_to": assigned_to,
                              "parent_task_id": parent_task_id, "project_id": project_id,
                              "relation_type": relation_type, "priority": priority})
        return f"ESK-{len(self.utworzone)}"


class _FakeMCPClientKatalog:
    """Atrapa MCP: tylko list_projects, do testu _resolve_person_id bez sieci
    (wzorzec z projectly_client_smoke_test.py)."""

    def __init__(self, people):
        self._people = people

    def call_tool(self, name, arguments=None):
        if name == "list_projects":
            return {"people": self._people, "projects": []}
        return {}


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

        # --- 1b. Anti-stacking: zadanie ŹRÓDŁOWE już ma prefiks -> NIE dokłada drugiego
        # (żywy bug 25-26.08.2026: "Wymaga decyzji: Wymaga decyzji: Wymaga decyzji: ...").
        projectly_stack = _FakeProjectlyClient()
        already_escalated_task = {"task_id": "T-ESK-2", "title": "Wymaga decyzji: Zadanie testowe",
                                  "project_id": "PROJ-1"}
        escalation.escalate_to_human(already_escalated_task, "Kolejny powód.", projectly_stack, assignee="pawel")
        checks.append(("escalate_to_human: BRAK podwójnego prefiksu, gdy zadanie już nim jest",
                       projectly_stack.utworzone[0]["title"] == "Wymaga decyzji: Zadanie testowe"))

        # --- 1c. Priorytet zadania eskalacji: PARKING (0) - czeka na decyzję
        # człowieka, bot nie ma go samo z siebie odbierać jako "do zrobienia teraz".
        checks.append(("escalate_to_human: zadanie eskalacji ma priorytet PARKING (0)",
                       projectly.utworzone[0]["priority"] == projectly_client.PRIORITY_PARKING))

        # --- 1d. continuation_task_creator: dziedziczy priorytet oryginału,
        # fallback "bieżące" gdy oryginał go nie niósł.
        projectly_kont = _FakeProjectlyClient()
        oryginal_z_priorytetem = {**TASK, "priority": projectly_client.PRIORITY_PRIORYTET}
        escalation.continuation_task_creator(oryginal_z_priorytetem, "Zatwierdzam.", projectly_kont)
        checks.append(("continuation_task_creator: dziedziczy priorytet oryginalnego zadania",
                       projectly_kont.utworzone[0]["priority"] == projectly_client.PRIORITY_PRIORYTET))

        projectly_kont_bez = _FakeProjectlyClient()
        escalation.continuation_task_creator(TASK, "Zatwierdzam.", projectly_kont_bez)
        checks.append(("continuation_task_creator: brak priorytetu w oryginale -> fallback BIEŻĄCE (4)",
                       projectly_kont_bez.utworzone[0]["priority"] == projectly_client.PRIORITY_BIEZACE))

        # --- 1e. Żywy bug znaleziony 29.08.2026: `priority or BIEŻĄCE` traktuje
        # priority=0 (PARKING) jako falsy i błędnie podbija zaparkowane zadanie
        # do BIEŻĄCE. Oryginał z priorytetem PARKING musi zostać na PARKING.
        projectly_kont_parking = _FakeProjectlyClient()
        oryginal_zaparkowany = {**TASK, "priority": projectly_client.PRIORITY_PARKING}
        escalation.continuation_task_creator(oryginal_zaparkowany, "Zatwierdzam.", projectly_kont_parking)
        checks.append(("continuation_task_creator: priority=0 (PARKING) w oryginale NIE jest podbijane do BIEŻĄCE",
                       projectly_kont_parking.utworzone[0]["priority"] == projectly_client.PRIORITY_PARKING))

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

        # --- 5. _resolve_person_id: nierozpoznana nazwa musi WYRAŹNIE ostrzec w
        # logu (żywy, niezdiagnozowany do końca incydent 23.08.2026: eskalacje
        # lądowały bez przypisania, cicho) — a celowo puste unassigned_pool NIE. ---
        real_client = projectly_client.ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
        real_client._mcp = _FakeMCPClientKatalog([{"id": "U1", "name": "Paweł"}])

        buf_typo = io.StringIO()
        with contextlib.redirect_stdout(buf_typo):
            resolved_typo = real_client._resolve_person_id("Paweł Literowka")
        checks.append(("_resolve_person_id: nierozpoznana nazwa -> None", resolved_typo is None))
        checks.append(("_resolve_person_id: nierozpoznana nazwa -> WYRAŹNE ostrzeżenie w logu z nazwą",
                       "[projectly_client]" in buf_typo.getvalue() and "Paweł Literowka" in buf_typo.getvalue()))

        buf_pool = io.StringIO()
        with contextlib.redirect_stdout(buf_pool):
            resolved_pool = real_client._resolve_person_id("unassigned_pool")
        checks.append(("_resolve_person_id: unassigned_pool (celowo bez przypisania) -> None BEZ ostrzeżenia",
                       resolved_pool is None and buf_pool.getvalue() == ""))

        buf_ok = io.StringIO()
        with contextlib.redirect_stdout(buf_ok):
            resolved_ok = real_client._resolve_person_id("Paweł")
        checks.append(("_resolve_person_id: nazwa rozpoznana -> id, bez ostrzeżenia",
                       resolved_ok == "U1" and buf_ok.getvalue() == ""))

        # --- 6. escalate_to_human bez podania assignee używa wartości z
        # config/projectly.yaml (escalation_default_assignee), NIE hardcoded
        # "pawel" w sygnaturze (żywy bug 23.08.2026, patrz _escalation_default_assignee). ---
        oryginalny_load_config = escalation._load_projectly_config
        try:
            escalation._load_projectly_config = lambda: {"escalation_default_assignee": "Zenon Testowy"}
            checks.append(("_escalation_default_assignee: czyta z config/projectly.yaml (nie hardcoded)",
                           escalation._escalation_default_assignee() == "Zenon Testowy"))

            projectly_bez_assignee = _FakeProjectlyClient()
            escalation.escalate_to_human(TASK, "Powód bez jawnego assignee.", projectly_bez_assignee)
            checks.append(("escalate_to_human bez assignee: przypisuje wg configu, NIE hardcoded 'pawel'",
                           projectly_bez_assignee.utworzone[0]["assigned_to"] == "Zenon Testowy"))

            escalation._load_projectly_config = lambda: (_ for _ in ()).throw(RuntimeError("config uszkodzony"))
            checks.append(("_escalation_default_assignee: config nieczytelny -> fail-closed fallback 'pawel'",
                           escalation._escalation_default_assignee() == "pawel"))
        finally:
            escalation._load_projectly_config = oryginalny_load_config
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
