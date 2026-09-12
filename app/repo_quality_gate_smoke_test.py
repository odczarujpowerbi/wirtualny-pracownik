"""
Test dymny repo_quality_gate.py. Zero uruchamiania prawdziwych testow:
runner podmieniany, repozytoria to katalogi tymczasowe z pustymi plikami.

Uzycie:
    python repo_quality_gate_smoke_test.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import repo_quality_gate


class _Wynik:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _repo(pliki=None, katalogi=None):
    repo = Path(tempfile.mkdtemp())
    for nazwa, tresc in (pliki or {}).items():
        sciezka = repo / nazwa
        sciezka.parent.mkdir(parents=True, exist_ok=True)
        sciezka.write_text(tresc, encoding="utf-8")
    for katalog in katalogi or []:
        (repo / katalog).mkdir(parents=True, exist_ok=True)
    return repo


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    zapamietane = {}

    def runner_ok(cmd, **kwargs):
        zapamietane["cmd"] = cmd
        zapamietane["cwd"] = kwargs.get("cwd")
        return _Wynik(0, stdout="85/85 testow przeszlo")

    def runner_blad(cmd, **kwargs):
        return _Wynik(1, stdout="2 testy padly", stderr="AssertionError")

    def runner_timeout(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 900)

    def runner_brak_narzedzia(cmd, **kwargs):
        raise OSError("npm: nie znaleziono polecenia")

    # 1. Wykrywanie polecenia po zawartosci repozytorium.
    checks.append(("self_check.py -> python self_check.py",
                   repo_quality_gate.wykryj_polecenie(_repo({"self_check.py": ""}))
                   == ["python", "self_check.py"]))
    checks.append(("app/self_check.py -> python app/self_check.py",
                   repo_quality_gate.wykryj_polecenie(_repo({"app/self_check.py": ""}))
                   == ["python", "app/self_check.py"]))
    checks.append(("package.json ze skryptem test -> npm test",
                   repo_quality_gate.wykryj_polecenie(
                       _repo({"package.json": json.dumps({"scripts": {"test": "node --test"}})}))
                   == ["npm", "test"]))
    checks.append(("Zaslepka 'no test specified' NIE jest testami",
                   repo_quality_gate.wykryj_polecenie(
                       _repo({"package.json": json.dumps(
                           {"scripts": {"test": 'echo "Error: no test specified" && exit 1'}})}))
                   is None))
    checks.append(("Katalog tests/ -> pytest",
                   repo_quality_gate.wykryj_polecenie(_repo(katalogi=["tests"])) == ["pytest", "-q"]))
    checks.append(("Repozytorium bez testow -> brak polecenia",
                   repo_quality_gate.wykryj_polecenie(_repo({"README.md": "nic"})) is None))
    checks.append(("quality_gate z konfiguracji ma pierwszenstwo",
                   repo_quality_gate.wykryj_polecenie(_repo({"self_check.py": ""}),
                                                      {"quality_gate": "make test"})
                   == ["make", "test"]))

    # 2. Wynik bramki.
    repo = _repo({"self_check.py": ""})
    zielona = repo_quality_gate.sprawdz(repo, runner=runner_ok)
    checks.append(("Testy przeszly -> bramka zielona", zielona["zielona"] is True))
    checks.append(("Bramka uruchamia polecenie W REPOZYTORIUM zadania",
                   zapamietane["cwd"] == str(repo)))
    checks.append(("Log testow trafia do wyniku", "85/85" in zielona["log"]))

    czerwona = repo_quality_gate.sprawdz(repo, runner=runner_blad)
    checks.append(("Testy padly -> bramka czerwona", czerwona["zielona"] is False))
    checks.append(("Czerwona bramka niesie log bledu", "AssertionError" in czerwona["log"]))

    # 3. Repozytorium bez testow przechodzi (nowy projekt musi moc cokolwiek scalic).
    bez_testow = repo_quality_gate.sprawdz(_repo({"README.md": "nic"}), runner=runner_ok)
    checks.append(("Repozytorium bez testow -> zielona, z opisem powodu",
                   bez_testow["zielona"] is True and "nie ma czego sprawdzić" in bez_testow["powod"]))

    # 4. Error case: timeout i brak narzedzia sa CZERWONE (fail-closed).
    checks.append(("Timeout testow -> czerwona, nie zielona",
                   repo_quality_gate.sprawdz(repo, runner=runner_timeout)["zielona"] is False))
    brak = repo_quality_gate.sprawdz(repo, runner=runner_brak_narzedzia)
    checks.append(("Brak narzedzia do testow -> czerwona (nie wiemy, wiec nie scalamy)",
                   brak["zielona"] is False and "nie udało się uruchomić" in brak["powod"]))

    print("\n--- Wynik testu dymnego repo_quality_gate ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'OK  ' if passed else 'BLAD'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedl.")
        sys.exit(1)
    print("\nWszystkie testy przeszly.")


if __name__ == "__main__":
    run()
