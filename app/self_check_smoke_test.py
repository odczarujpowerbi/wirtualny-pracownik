"""
Test dymny samo-weryfikacji (self_check.py) i auto-pull (repo_updater.py).
Nie dotyka prawdziwych testów ani git — używa tymczasowego katalogu z atrapami
testów i wstrzykiwanego runnera dla git.

Użycie:
    python self_check_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import repo_updater
import self_check


class _FakeProc:
    def __init__(self, returncode, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "aaa_smoke_test.py").write_text("print('dobrze')\n", encoding="utf-8")
        (tmp / "bbb_smoke_test.py").write_text("import sys; print('zle'); sys.exit(1)\n", encoding="utf-8")
        (tmp / "nie_test.py").write_text("raise SystemExit(1)\n", encoding="utf-8")

        found = self_check.discover_tests(tmp)
        checks.append(("discover_tests: tylko *_smoke_test.py (2 z 3 plików)", len(found) == 2))

        ok = self_check.run_one(tmp / "aaa_smoke_test.py")
        checks.append(("run_one: przechodzący test -> ok=True", ok["ok"] is True))

        bad = self_check.run_one(tmp / "bbb_smoke_test.py")
        checks.append(("run_one: padający test -> ok=False, wyjście złapane",
                       bad["ok"] is False and "zle" in bad["output"]))

        try:
            self_check.run_self_check(test_dir=tmp)
            raised = False
        except RuntimeError:
            raised = True
        checks.append(("run_self_check: padający test -> rzuca (czerwony w dashboardzie)", raised))

        # Katalog z samymi przechodzącymi -> zwraca podsumowanie, nie rzuca.
        (tmp / "bbb_smoke_test.py").unlink()
        res = self_check.run_self_check(test_dir=tmp)
        checks.append(("run_self_check: same przechodzące -> podsumowanie", res["passed"] == 1))

    # EXCLUDE: bootstrap_smoke_test nie wchodzi do ciągłej samo-weryfikacji.
    real = [t.name for t in self_check.discover_tests()]
    checks.append(("discover_tests: bootstrap_smoke_test wykluczony",
                   "bootstrap_smoke_test.py" not in real and len(real) > 0))

    # repo_updater: sukces (runner udający git) -> zwraca output, nie rzuca.
    ok_pull = repo_updater.run_update(runner=lambda *a, **k: _FakeProc(0, "Already up to date."))
    checks.append(("repo_updater: pull OK -> zwraca output", "up to date" in ok_pull["output"]))

    # repo_updater: błąd git -> RuntimeError (error case).
    try:
        repo_updater.run_update(runner=lambda *a, **k: _FakeProc(1, "", "fatal: conflict"))
        pull_raised = False
    except RuntimeError:
        pull_raised = True
    checks.append(("repo_updater: pull błąd -> RuntimeError", pull_raised))

    print("\n--- Wynik testu dymnego samo-weryfikacji ---")
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
