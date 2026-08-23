"""
Test dymny scheduler_lock. Zero sieci, zero realnych procesów — psutil
podmieniony na atrapę przez sys.modules, żeby test kontrolował "kto żyje"
bez zależności od realnych PID-ów maszyny.

Użycie:
    python scheduler_lock_smoke_test.py
"""

import os
import sys
import types

import scheduler_lock as lock


def _install_fake_psutil(alive_pids, cmdlines):
    """alive_pids: zbiór PID-ów uznawanych za żywe. cmdlines: {pid: str}
    zwracane przez Process(pid).cmdline() (jako pojedyncza lista słów)."""
    fake = types.ModuleType("psutil")

    class FakeProcess:
        def __init__(self, pid):
            if pid not in alive_pids:
                raise fake.Error(f"nie istnieje: {pid}")
            self._pid = pid

        def cmdline(self):
            return cmdlines.get(self._pid, "").split()

    class FakeError(Exception):
        pass

    fake.Error = FakeError
    fake.pid_exists = lambda pid: pid in alive_pids
    fake.Process = FakeProcess
    sys.modules["psutil"] = fake


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_lock_path = lock.LOCK_PATH
    original_psutil = sys.modules.get("psutil")

    try:
        import tempfile
        from pathlib import Path

        tmp_dir = Path(tempfile.mkdtemp())
        lock.LOCK_PATH = tmp_dir / "job_scheduler.lock"

        # 1. Brak blokady -> acquire() się udaje.
        r = lock.acquire(pid=111)
        checks.append(("acquire: brak blokady -> ok True", r["ok"] is True))
        checks.append(("acquire: zapisuje własny PID", lock._read()["pid"] == 111))

        # 2. Druga instancja (inny PID), pierwsza WCIĄŻ ŻYJE (fake psutil) -> odmowa.
        _install_fake_psutil(alive_pids={111}, cmdlines={111: "python job_scheduler.py"})
        r2 = lock.acquire(pid=222)
        checks.append(("acquire: żywa instancja (111) -> odmowa dla nowej (222)", r2["ok"] is False))
        checks.append(("acquire: blokada wciąż na PID 111 (nie nadpisana)", lock._read()["pid"] == 111))

        # 3. release() przez proces, który NIE trzyma blokady -> nic nie robi.
        released_wrong = lock.release(pid=222)
        checks.append(("release: cudzy PID -> False, blokada zostaje", released_wrong is False and lock._read() is not None))

        # 4. release() przez właściciela -> zwalnia.
        released_owner = lock.release(pid=111)
        checks.append(("release: właściciel (111) -> True, plik usunięty", released_owner is True and lock._read() is None))

        # 5. PID istnieje, ale cmdline NIE jest job_scheduler (PID odzyskany przez inny proces) -> martwa, przejmowana.
        lock.acquire(pid=333)
        _install_fake_psutil(alive_pids={333}, cmdlines={333: "notepad.exe"})
        r3 = lock.acquire(pid=444)
        checks.append(("acquire: PID żyje, ale to NIE job_scheduler (odzyskany PID) -> przejmuje", r3["ok"] is True))
        checks.append(("acquire: po przejęciu blokada na nowym PID (444)", lock._read()["pid"] == 444))

        # 6. Martwy proces (psutil.pid_exists=False) -> blokada przejmowana automatycznie.
        _install_fake_psutil(alive_pids=set(), cmdlines={})
        r4 = lock.acquire(pid=555)
        checks.append(("acquire: martwy proces -> przejmuje blokadę", r4["ok"] is True))
        checks.append(("acquire: blokada teraz na nowym PID (555)", lock._read()["pid"] == 555))

    finally:
        lock.LOCK_PATH = original_lock_path
        if original_psutil is not None:
            sys.modules["psutil"] = original_psutil
        else:
            sys.modules.pop("psutil", None)

    print("\n--- Wynik testu dymnego scheduler_lock ---")
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
