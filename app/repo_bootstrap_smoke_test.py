"""
Test dymny repo_bootstrap.py. Zero sieci i zero prawdziwego GitHuba:
opener (urllib) i runner (git/gh) podmieniane, repozytorium to katalog tymczasowy.

Uzycie:
    python repo_bootstrap_smoke_test.py
"""

import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path

import repo_bootstrap


class _Wynik:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _Odpowiedz(io.BytesIO):
    """Minimalny kontekst menedzera, jak obiekt z urlopen."""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def _opener_ok(request, timeout=None):
    return _Odpowiedz(json.dumps({"clone_url": "https://github.com/firma/projekt.git"}).encode("utf-8"))


def _opener_odmowa(request, timeout=None):
    raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)


def _runner_ok(cmd, **kwargs):
    return _Wynik(0)


def _runner_gh_pada(cmd, **kwargs):
    return _Wynik(1, stderr="gh: not logged in")


class _Klient:
    def __init__(self):
        self.zapisane = []

    def set_project_repo(self, project_id, repo_url, repo_local_path):
        self.zapisane.append((project_id, repo_url, repo_local_path))
        return {"id": project_id}


class _KlientPadajacy(_Klient):
    def set_project_repo(self, project_id, repo_url, repo_local_path):
        raise RuntimeError("Projectly odmowilo zapisu")


def _sandbox():
    katalog = Path(tempfile.mkdtemp()) / "projekt"
    katalog.mkdir(parents=True)
    return {"ok": True, "tryb": "init", "path": str(katalog), "branch": "agent/t-1-zaloz",
            "base_branch": "main", "config": {"github_owner": "firma"}}


TASK = {"task_id": "T-1", "title": "Zainicjuj repozytorium", "project_id": "P-1"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    stary_token = os.environ.get("GITHUB_TOKEN")

    try:
        # 1. Happy path: token dziala, repozytorium powstaje, adresy trafiaja do Projectly.
        os.environ["GITHUB_TOKEN"] = "token-testowy"
        klient = _Klient()
        sandbox = _sandbox()
        wynik = repo_bootstrap.dokoncz(klient, TASK, sandbox, runner=_runner_ok, opener=_opener_ok)

        checks.append(("Token GitHuba: repozytorium zalozone", wynik["ok"] is True))
        checks.append(("Adres repozytorium wraca w wyniku",
                       wynik["url"] == "https://github.com/firma/projekt.git"))
        checks.append(("Adresy zapisane w Projectly (projekt, url, folder)",
                       klient.zapisane == [("P-1", "https://github.com/firma/projekt.git",
                                            sandbox["path"])]))

        # 2. Error case: brak tokenu i brak gh -> repozytorium ZOSTAJE lokalne,
        #    w Projectly NIC nie zapisujemy (zero cichego sukcesu).
        os.environ.pop("GITHUB_TOKEN", None)
        klient2 = _Klient()
        wynik2 = repo_bootstrap.dokoncz(klient2, TASK, _sandbox(), runner=_runner_gh_pada,
                                        opener=_opener_ok)
        checks.append(("Brak dostepu do GitHuba: ok=False", wynik2["ok"] is False))
        checks.append(("Brak dostepu do GitHuba: powod mowi o braku tokenu",
                       "GITHUB_TOKEN" in wynik2["powod"]))
        checks.append(("Brak dostepu do GitHuba: NIC nie zapisane w Projectly", klient2.zapisane == []))

        # 3. Error case: GitHub odmawia (403) i gh tez nie dziala.
        os.environ["GITHUB_TOKEN"] = "token-bez-uprawnien"
        wynik3 = repo_bootstrap.dokoncz(_Klient(), TASK, _sandbox(), runner=_runner_gh_pada,
                                        opener=_opener_odmowa)
        checks.append(("Odmowa GitHuba: ok=False i kod bledu w powodzie",
                       wynik3["ok"] is False and "403" in wynik3["powod"]))

        # 4. Error case: repozytorium powstalo, ale Projectly nie przyjelo adresu.
        os.environ["GITHUB_TOKEN"] = "token-testowy"
        wynik4 = repo_bootstrap.dokoncz(_KlientPadajacy(), TASK, _sandbox(),
                                        runner=_runner_ok, opener=_opener_ok)
        checks.append(("Blad zapisu w Projectly: ok=False, ale powod mowi ze repo istnieje",
                       wynik4["ok"] is False and "repozytorium powstalo" in wynik4["powod"]))

        # 5. To nie jest zakladanie nowego repozytorium -> nic nie robimy.
        klon = {**_sandbox(), "tryb": "clone"}
        checks.append(("Zwykly klon: modul nie robi nic",
                       repo_bootstrap.dokoncz(_Klient(), TASK, klon, runner=_runner_ok,
                                              opener=_opener_ok)["ok"] is False))

        # 6. Brak projektu w zadaniu -> nie mamy gdzie zapisac adresow.
        checks.append(("Zadanie bez projektu: ok=False, bez wyjatku",
                       repo_bootstrap.dokoncz(_Klient(), {"task_id": "T-2"}, _sandbox(),
                                              runner=_runner_ok, opener=_opener_ok)["ok"] is False))
    finally:
        if stary_token is None:
            os.environ.pop("GITHUB_TOKEN", None)
        else:
            os.environ["GITHUB_TOKEN"] = stary_token

    print("\n--- Wynik testu dymnego repo_bootstrap ---")
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
