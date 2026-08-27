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


def test_recurring_job_failure_deduplicated_same_day():
    # Wzorzec "job" nie jest chroniony kursorem zdarzen (job_health liczy sie
    # zawsze od nowa z load_history) — dedup opiera sie WYLACZNIE na kluczu
    # "job:{nazwa}:{dzien}" w state["repair_tasks"]. Ten test sprawdza, ze
    # DRUGI przebieg z ta sama historia bledow NIE dubluje zadania.
    _use_temp_db()
    import job_scheduler
    history = [
        {"id": f"r{i}", "name": "runner_loop", "run_at": NOW, "status": "error",
         "error": "boom", "duration_seconds": 1.0, "trigger": "schedule", "result": None}
        for i in range(4)
    ]
    original_load_history = job_scheduler.load_history
    job_scheduler.load_history = lambda limit=100, include_output=False: history
    try:
        client = _FakeClient()
        state_path = _temp_state_path()
        kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=state_path)
        kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=state_path)
    finally:
        job_scheduler.load_history = original_load_history

    assert len(client.created_tasks) == 1, "drugi przebieg tego samego dnia nie powinien dublowac zadania dla joba"
    print("OK  wzorzec job: deduplikacja per dzien chroni przed powtornym zadaniem")


def test_job_failure_below_threshold_does_not_escalate():
    # Logika progowa _job_health: 2/10 bledow < job_failure_threshold=3 ->
    # brak zadania naprawczego.
    _use_temp_db()
    import job_scheduler
    history = [
        {"id": "ok1", "name": "runner_loop", "run_at": NOW, "status": "ok",
         "error": None, "duration_seconds": 1.0, "trigger": "schedule", "result": None},
        {"id": "err1", "name": "runner_loop", "run_at": NOW, "status": "error",
         "error": "boom", "duration_seconds": 1.0, "trigger": "schedule", "result": None},
        {"id": "err2", "name": "runner_loop", "run_at": NOW, "status": "error",
         "error": "boom", "duration_seconds": 1.0, "trigger": "schedule", "result": None},
    ]
    original_load_history = job_scheduler.load_history
    job_scheduler.load_history = lambda limit=100, include_output=False: history
    try:
        client = _FakeClient()
        kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=_temp_state_path())
    finally:
        job_scheduler.load_history = original_load_history

    assert client.created_tasks == [], "2 bledy na 3 przebiegi ponizej progu 3 nie powinny tworzyc zadania"
    print("OK  wzorzec job: 2 bledy < prog 3 -> brak zadania naprawczego")


def test_slow_leak_across_cycles_not_detected():
    # Znane, udokumentowane ograniczenie (patrz TODO w kacper_monitor._skill_failures):
    # prog liczony jest per PARTIA zdarzen od ostatniego checkpointu, nie per
    # dzien lacznie. Powolny wyciek (1-2 niepowodzenia na cykl) przez wiele
    # cykli monitorowania moze NIGDY nie przekroczyc progu 3 w pojedynczej
    # partii, mimo ze w sumie tego dnia skill zawiodl znacznie wiecej razy
    # niz prog. Ten test SWIADOMIE demonstruje, ze zadanie naprawcze NIE
    # powstaje w takim scenariuszu — to nie jest bug do naprawienia w tym
    # zadaniu, tylko udokumentowany trade-off czulosc/szum.
    _use_temp_db()
    state_path = _temp_state_path()
    client = _FakeClient()

    total_failures_injected = 0
    for cycle in range(4):
        # 2 nowe niepowodzenia na cykl -> ponizej progu 3 w KAZDEJ partii,
        # ale 4 cykle x 2 = 8 niepowodzen tego samego skilla w ciagu dnia.
        for i in range(2):
            state_store.record_event(
                f"LEAK-{cycle}-{i}", "skill_usage:pbip_validate:failure", "wolny wyciek", NOW,
            )
            total_failures_injected += 1
        kacper_monitor.run_monitor_cycle(client=client, thresholds=THRESHOLDS, state_path=state_path)

    assert total_failures_injected == 8, "8 niepowodzen tego samego skilla w ciagu dnia, znacznie powyzej progu 3"
    assert client.created_tasks == [], (
        "znane ograniczenie: powolny wyciek (2 na cykl) nigdy nie przekracza progu "
        "3 w pojedynczej partii, wiec zadanie naprawcze NIE powstaje mimo 8 "
        "niepowodzen tego samego skilla w ciagu dnia"
    )
    print("OK  udokumentowane ograniczenie: powolny wyciek awarii (2/cykl) NIE wykryty mimo 8 niepowodzen dziennie")


if __name__ == "__main__":
    test_first_run_seeds_cursor_at_now_not_backlog()
    test_no_admin_project_fails_closed_no_task_created()
    test_repeated_skill_failure_creates_one_repair_task()
    test_single_failure_does_not_escalate()
    test_idempotent_cursor_does_not_reprocess()
    test_recurring_job_failure_creates_repair_task()
    test_recurring_job_failure_deduplicated_same_day()
    test_job_failure_below_threshold_does_not_escalate()
    test_slow_leak_across_cycles_not_detected()
    print("\nWszystkie testy Kacpra przeszły.")
