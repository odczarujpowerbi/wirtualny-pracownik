"""
Test dymny remote_control.py — sterowanie botem z poziomu Projectly przez
status jednego, stałego zadania kontrolnego. Zero sieci — klient Projectly to
atrapa. Izoluje control.RUNS_DIR i remote_control._state_path_for_role
(przez podmianę funkcji), zero wpływu na prawdziwy stan pauzy/plik tej maszyny.

Użycie:
    python remote_control_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import control
import remote_control as rc


class _FakeClient:
    def __init__(self, admin_project_id="ADMIN-PROJ", existing_tasks=None):
        self.utworzone = []
        self._admin_project_id = admin_project_id
        self._tasks = list(existing_tasks or [])

    def default_admin_project_id(self):
        return self._admin_project_id

    def list_tasks(self, project_id=None):
        return list(self._tasks)

    def create_task(self, title, description, assigned_to=None, project_id=None, **kwargs):
        task_id = f"CTRL-{len(self.utworzone) + 1:03d}"
        self.utworzone.append({"title": title, "assigned_to": assigned_to, "project_id": project_id})
        self._tasks.append({"task_id": task_id, "title": title, "status": "todo"})
        return task_id

    def set_status(self, task_id, status):
        for t in self._tasks:
            if t["task_id"] == task_id:
                t["status"] = status


def _isolate(tmp):
    control.RUNS_DIR = tmp
    rc._last_checked_at = None


def _temp_state_path_factory(tmp):
    def _f(role):
        return tmp / f"remote_control_state_{role}.json"
    return _f


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_state_path_for_role = rc._state_path_for_role
    original_runs_dir = control.RUNS_DIR

    try:
        # --- 1. Zadanie kontrolne NIE istnieje -> tworzy je RAZ, status
        # domyślny "todo" -> bot NIE jest wstrzymywany (todo != "done"). ---
        tmp1 = Path(tempfile.mkdtemp())
        _isolate(tmp1)
        rc._state_path_for_role = _temp_state_path_factory(tmp1)
        client1 = _FakeClient()
        status1 = rc.sync(client=client1, role="dev", force=True)
        checks.append(("sync: brak zadania kontrolnego -> tworzy RAZ", len(client1.utworzone) == 1))
        checks.append(("sync: nowo utworzone zadanie ma status 'todo' -> bot NIE wstrzymany",
                       status1 == "todo" and control.is_paused() is False))
        checks.append(("sync: tytuł zadania kontrolnego zawiera nazwę roli",
                       "dev" in client1.utworzone[0]["title"]))

        # Drugi sync (force) -> NIE tworzy drugiego zadania (cache task_id w stanie).
        rc.sync(client=client1, role="dev", force=True)
        checks.append(("sync: kolejne wywołanie NIE dubluje zadania kontrolnego", len(client1.utworzone) == 1))

        # --- 2. Status "done" -> bot WSTRZYMANY. ---
        tmp2 = Path(tempfile.mkdtemp())
        _isolate(tmp2)
        rc._state_path_for_role = _temp_state_path_factory(tmp2)
        client2 = _FakeClient()
        rc.sync(client=client2, role="checker", force=True)
        task_id2 = client2.utworzone[0]
        real_task_id2 = client2._tasks[0]["task_id"]
        client2.set_status(real_task_id2, "done")
        status2 = rc.sync(client=client2, role="checker", force=True)
        checks.append(("sync: status 'done' -> bot WSTRZYMANY", status2 == "done" and control.is_paused() is True))

        # --- 3. Status wraca na 'todo' -> bot WZNOWIONY (bo TEN mechanizm go wstrzymał). ---
        client2.set_status(real_task_id2, "todo")
        status3 = rc.sync(client=client2, role="checker", force=True)
        checks.append(("sync: status wraca na 'todo' -> bot WZNOWIONY (ten sam mechanizm)",
                       status3 == "todo" and control.is_paused() is False))

        # --- 4. NIE nadpisuje ręcznej pauzy z dashboardu (inny powód). ---
        tmp3 = Path(tempfile.mkdtemp())
        _isolate(tmp3)
        rc._state_path_for_role = _temp_state_path_factory(tmp3)
        client3 = _FakeClient()
        rc.sync(client=client3, role="marketing", force=True)
        control.pause(reason="Wstrzymano z panelu operatora.")  # ręczna pauza, INNY powód
        status4 = rc.sync(client=client3, role="marketing", force=True)  # status wciąż 'todo'
        checks.append(("sync: NIE cofa ręcznej pauzy z dashboardu (inny powód niż marker)",
                       control.is_paused() is True and control.pause_reason() == "Wstrzymano z panelu operatora."))

        # --- 5. NIE nadpisuje istniejącego powodu pauzy, gdy status='done' ale
        # bot już wstrzymany z innego powodu (nie dubluje/nie zmienia powodu). ---
        real_task_id3 = client3._tasks[0]["task_id"]
        client3.set_status(real_task_id3, "done")
        rc.sync(client=client3, role="marketing", force=True)
        checks.append(("sync: status='done', ale już wstrzymany innym powodem -> powód NIETKNIĘTY",
                       control.pause_reason() == "Wstrzymano z panelu operatora."))

        # --- 6. Throttling: bez force, drugie wywołanie w tym samym momencie -> no-op. ---
        tmp4 = Path(tempfile.mkdtemp())
        _isolate(tmp4)
        rc._state_path_for_role = _temp_state_path_factory(tmp4)
        client4 = _FakeClient()
        rc.sync(client=client4, role="dev", force=True)
        wywolania_przed = len(client4.utworzone)
        rc.sync(client=client4, role="dev")  # bez force, throttled -> nie woła list_tasks/create_task ponownie
        checks.append(("sync: throttling bez force -> brak dodatkowego zapytania", len(client4.utworzone) == wywolania_przed))

        # --- 7. Fail-soft: klient rzuca wyjątek -> stan pauzy NIETKNIĘTY, brak wyjątku. ---
        tmp5 = Path(tempfile.mkdtemp())
        _isolate(tmp5)
        rc._state_path_for_role = _temp_state_path_factory(tmp5)

        class _BoomClient:
            def default_admin_project_id(self):
                raise RuntimeError("Symulowany błąd sieci Projectly.")
        control.pause(reason="stan sprzed błędu")
        wynik_bledu = rc.sync(client=_BoomClient(), role="dev", force=True)
        checks.append(("sync: błąd klienta -> zwraca None, BEZ wyjątku, stan pauzy nietknięty",
                       wynik_bledu is None and control.is_paused() is True
                       and control.pause_reason() == "stan sprzed błędu"))

        # --- 8. Brak default_admin_project_id -> fail-closed, brak utworzenia zadania. ---
        tmp6 = Path(tempfile.mkdtemp())
        _isolate(tmp6)
        rc._state_path_for_role = _temp_state_path_factory(tmp6)
        client6 = _FakeClient(admin_project_id=None)
        wynik_brak_projektu = rc.sync(client=client6, role="dev", force=True)
        checks.append(("sync: brak default_admin_project_id -> None, zero utworzonych zadań",
                       wynik_brak_projektu is None and len(client6.utworzone) == 0))
    finally:
        rc._state_path_for_role = original_state_path_for_role
        control.RUNS_DIR = original_runs_dir
        rc._last_checked_at = None

    print("\n--- Wynik testu dymnego remote_control ---")
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
