"""
Test dymny kacper_monitor.py (rola "Kacper" — monitor i samo-naprawa).
Używa TYMCZASOWEJ bazy (podmiana state_store.DB_PATH) i tymczasowego stanu
Kacpra — nie dotyka żywego runs/state.db ani runs/kacper_state.json.
Wpina się automatycznie w self_check.py.
"""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import kacper_monitor
import state_store

NOW = datetime.now(timezone.utc).isoformat()
THRESHOLDS = {
    "job_failure_threshold": 3, "job_failure_window": 10,
    "skill_failure_threshold": 3, "alert_assignee": "pawel",
}


class _FakeClient:
    def __init__(self):
        self.created_tasks = []
        self.published = []

    def create_task(self, title, description, assigned_to=None, **kwargs):
        task_id = f"KAC-{len(self.created_tasks) + 1:03d}"
        self.created_tasks.append({"task_id": task_id, "title": title, "description": description})
        return task_id

    def default_admin_project_id(self):
        return "FAKE-ADMIN-PROJECT"

    def publish_status(self, role, payload):
        self.published.append((role, payload))
        return True


def _use_temp_db():
    state_store.DB_PATH = Path(tempfile.mkdtemp()) / "test_state.db"


def _temp_state_path():
    """Ścieżka stanu z JUŻ ZAPISANYM kursorem last_event_id=0 — testy detekcji
    (poniżej) wstawiają zdarzenia PRZED pierwszym przebiegiem i sprawdzają, że
    Kacper je widzi. Prawdziwe "pierwsze włączenie" (kursor od 'teraz', nie od
    zera) ma osobny test: test_first_run_seeds_cursor_at_now_not_backlog."""
    import json
    path = Path(tempfile.mkdtemp()) / "kacper_state.json"
    path.write_text(json.dumps({"last_event_id": 0, "repair_tasks": {}}), encoding="utf-8")
    return path


def test_first_run_seeds_cursor_at_now_not_backlog():
    # Żywy incydent 21.08.2026: pierwszy ręczny przebieg Kacpra na prawdziwym
    # dzienniku trafił w limit 2000 zdarzeń i zalozyl zadanie naprawcze na
    # podstawie STAREJ historii. Kacper ma monitorowac od chwili wlaczenia,
    # nie retroaktywnie cala historie.
    _use_temp_db()
    for i in range(5):
        state_store.record_event(f"OLD-{i}", "skill_usage:pbip_validate:failure", "stara historia", NOW)

    never_run_state_path = Path(tempfile.mkdtemp()) / "kacper_state.json"
    assert not never_run_state_path.exists()

    client = _FakeClient()
    summary = kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=never_run_state_path)
    assert summary["events_scanned"] == 0, "pierwszy przebieg nie powinien widziec starych zdarzen"
    assert client.created_tasks == [], "pierwszy przebieg nie powinien tworzyc zadan z historii sprzed wlaczenia"
    print("OK  pierwsze wlaczenie: kursor od 'teraz', stara historia (5x failure) nie tworzy zadania")


def test_no_admin_project_fails_closed_no_task_created():
    # Realny Projectly (create_task) wymaga project_id; bez skonfigurowanego/
    # rozpoznanego default_admin_project Kacper NIE zgaduje projekt — zostaje
    # tylko log + publish_status, żaden zadanie naprawcze nie powstaje.
    _use_temp_db()
    for i in range(3):
        state_store.record_event(f"T-{i}", "skill_usage:pbip_validate:failure", "boom", NOW)

    client = _FakeClient()
    client.default_admin_project_id = lambda: None
    summary = kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=_temp_state_path())
    assert client.created_tasks == [], "bez project_id nie wolno tworzyc zadania w Projectly"
    assert summary["repair_tasks_created"][0]["task_id"] is None
    print("OK  brak default_admin_project -> fail-closed, zero zadan w Projectly")


def test_repeated_skill_failure_creates_one_repair_task():
    _use_temp_db()
    for i in range(3):
        state_store.record_event(f"T-{i}", "skill_usage:pbip_validate:failure", "boom", NOW)

    client = _FakeClient()
    summary = kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=_temp_state_path())
    assert len(client.created_tasks) == 1, client.created_tasks
    assert "pbip_validate" in client.created_tasks[0]["title"]
    assert summary["events_scanned"] == 3
    print("OK  3x skill_usage:...:failure -> jedno zadanie naprawcze")


def test_single_failure_does_not_escalate():
    _use_temp_db()
    state_store.record_event("T-1", "skill_usage:pbip_validate:failure", "boom", NOW)
    state_store.record_event("T-2", "gate_failed", "drobna uwaga", NOW)

    client = _FakeClient()
    kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=_temp_state_path())
    assert client.created_tasks == [], "jedno niepowodzenie nie powinno tworzyc zadania naprawczego"
    print("OK  pojedyncze niepowodzenie nie tworzy zadania naprawczego (unika duplikatu z runner_loop)")


def test_idempotent_cursor_does_not_reprocess():
    _use_temp_db()
    state_path = _temp_state_path()
    for i in range(3):
        state_store.record_event(f"T-{i}", "skill_usage:web_fetch:failure", "boom", NOW)

    client = _FakeClient()
    kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=state_path)
    assert len(client.created_tasks) == 1

    # drugi przebieg BEZ nowych zdarzen -> kursor juz przesuniety, zero nowych zadan
    summary2 = kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=state_path)
    assert summary2["events_scanned"] == 0
    assert len(client.created_tasks) == 1, "drugi przebieg bez nowych zdarzen nie powinien dublowac zadania"
    print("OK  kursor (last_event_id) chroni przed ponownym przetworzeniem tych samych zdarzen")


def test_recurring_job_failure_creates_repair_task(monkeypatch=None):
    _use_temp_db()
    import job_scheduler
    history = [
        {"id": f"r{i}", "name": "runner_loop", "run_at": NOW, "status": "error",
         "error": "Extra data: line 1 column 1", "duration_seconds": 1.0, "trigger": "schedule", "result": None}
        for i in range(4)
    ]
    original_load_history = job_scheduler.load_history
    job_scheduler.load_history = lambda limit=100, include_output=False: history
    try:
        client = _FakeClient()
        kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=_temp_state_path())
    finally:
        job_scheduler.load_history = original_load_history

    assert len(client.created_tasks) == 1
    assert "runner_loop" in client.created_tasks[0]["title"]
    print("OK  praca cykliczna zawodzaca powtarzalnie (4/4 error) -> jedno zadanie naprawcze")


if __name__ == "__main__":
    test_first_run_seeds_cursor_at_now_not_backlog()
    test_no_admin_project_fails_closed_no_task_created()
    test_repeated_skill_failure_creates_one_repair_task()
    test_single_failure_does_not_escalate()
    test_idempotent_cursor_does_not_reprocess()
    test_recurring_job_failure_creates_repair_task()
    print("\nWszystkie testy Kacpra przeszły.")
