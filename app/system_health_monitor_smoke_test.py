"""
Test dymny system_health_monitor.py. Zero sieci — klient Projectly to atrapa.
Używa tymczasowego pliku stanu (nie dotyka żywego runs/system_health_state.json).

Kluczowy przypadek (żywy bug 26.08.2026, znaleziony w audycie 27.08.2026):
brak deduplikacji tworzył NOWE zadanie "Alert: stan maszyny..." w Projectly
przy KAŻDYM przebiegu ze status=critical — 10 prawie identycznych zadań w
20 minut, podczas gdy RAM spadał do wyczerpania. Testy pilnują, że jeden
epizod critical tworzy DOKŁADNIE jedno zadanie, a powrót do "ok" resetuje
deduplikację (kolejny, NOWY epizod critical dostaje nowe zadanie).

Użycie:
    python system_health_monitor_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import system_health_monitor as shm

THRESHOLDS = {"min_available_ram_percent": 10, "expected_scripts": ["job_scheduler.py"],
              "alert_assignee": "pawel"}


class _FakeClient:
    def __init__(self, admin_project_id="FAKE-ADMIN-PROJECT"):
        self.created_tasks = []
        self.published = []
        self._admin_project_id = admin_project_id

    def create_task(self, title, description, assigned_to=None, **kwargs):
        task_id = f"HEALTH-{len(self.created_tasks) + 1:03d}"
        self.created_tasks.append({"task_id": task_id, "title": title, "description": description})
        return task_id

    def default_admin_project_id(self):
        return self._admin_project_id

    def publish_status(self, role, payload):
        self.published.append((role, payload))
        return True


def _snapshot(ram_percent, scripts=("job_scheduler.py",)):
    return {"timestamp": "2026-08-27T00:00:00+00:00", "ram_total_gb": 12.0,
            "ram_available_gb": 1.0, "ram_available_percent": ram_percent,
            "running_scripts": list(scripts)}


def _temp_state_path():
    return Path(tempfile.mkdtemp()) / "system_health_state.json"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- evaluate_health: progi ---
    zdrowe = shm.evaluate_health(_snapshot(50.0), THRESHOLDS)
    checks.append(("evaluate_health: RAM powyżej progu -> status ok", zdrowe["status"] == "ok"))

    krytyczne = shm.evaluate_health(_snapshot(2.4), THRESHOLDS)
    checks.append(("evaluate_health: RAM poniżej progu -> status critical", krytyczne["status"] == "critical"))
    checks.append(("evaluate_health: issue wspomina brakującą pamięć", any("RAM" in i for i in krytyczne["issues"])))

    brak_skryptu = shm.evaluate_health(_snapshot(50.0, scripts=()), THRESHOLDS)
    checks.append(("evaluate_health: brak oczekiwanego skryptu -> critical",
                   brak_skryptu["status"] == "critical"))

    # --- run_health_check: deduplikacja per epizod (NIE per cykl) ---
    original_gss = shm.get_system_snapshot
    original_get_client = shm.get_client
    try:
        state_path = _temp_state_path()
        client = _FakeClient()

        shm.get_system_snapshot = lambda: _snapshot(2.4)
        for _ in range(5):
            shm.run_health_check(client=client, thresholds=THRESHOLDS, state_path=state_path)
        checks.append(("5 kolejnych przebiegów critical -> DOKŁADNIE jedno zadanie w Projectly",
                       len(client.created_tasks) == 1))
        checks.append(("Tytuł zadania wspomina alert stanu maszyny",
                       "Alert" in client.created_tasks[0]["title"]))

        # Zdrowie wraca do normy — dedup dla tego epizodu ma się zresetować.
        shm.get_system_snapshot = lambda: _snapshot(50.0)
        shm.run_health_check(client=client, thresholds=THRESHOLDS, state_path=state_path)
        checks.append(("Powrót do ok -> nadal tylko jedno zadanie (bez nowego przy ok)",
                       len(client.created_tasks) == 1))

        # Nowy epizod critical tego samego dnia -> NOWE zadanie (nie zlewa się z poprzednim).
        shm.get_system_snapshot = lambda: _snapshot(1.0)
        shm.run_health_check(client=client, thresholds=THRESHOLDS, state_path=state_path)
        checks.append(("Nowy epizod critical po powrocie do ok -> drugie, NOWE zadanie",
                       len(client.created_tasks) == 2))

        # --- fail-closed: brak default_admin_project -> nie zgaduje, nie tworzy ---
        state_path2 = _temp_state_path()
        client_bez_projektu = _FakeClient(admin_project_id=None)
        shm.get_system_snapshot = lambda: _snapshot(1.0)
        wynik = shm.run_health_check(client=client_bez_projektu, thresholds=THRESHOLDS, state_path=state_path2)
        checks.append(("Brak default_admin_project -> created_task_id=None, fail-closed",
                       wynik["created_task_id"] is None and len(client_bez_projektu.created_tasks) == 0))

        # --- publish_status zawsze wywoływane, niezależnie od critical/ok ---
        checks.append(("publish_status wywoływane przy każdym przebiegu",
                       len(client.published) == 7))  # 5 + 1 (ok) + 1 (nowy critical)
    finally:
        shm.get_system_snapshot = original_gss
        shm.get_client = original_get_client

    print("\n--- Wynik testu dymnego system_health_monitor ---")
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
