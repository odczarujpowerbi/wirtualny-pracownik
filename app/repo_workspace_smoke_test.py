"""
Test dymny repo_workspace.py. Zero sieci: `git init` dziala na katalogu
tymczasowym, a nieudany klon jest symulowany podmienionym runnerem. Zadne
prawdziwe repozytorium (ani wirtualny-pracownik, ani klienta) nie jest dotykane.

Uzycie:
    python repo_workspace_smoke_test.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import repo_workspace

TASK_INIT = {"task_id": "T-NOWY", "title": "Zaloz nowy projekt landing page"}
TASK_URL = {"task_id": "T-URL", "title": "Popraw walidacje",
            "description": "Repo: https://github.com/przyklad/strona.git"}


class _WynikRunnera:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _konfiguracja(korzen, **nadpisania):
    return {**repo_workspace.load_config(), "sandbox_root": str(korzen), **nadpisania}


def _log(repo_dir):
    return subprocess.run(["git", "log", "--format=%s"], cwd=str(repo_dir),
                          capture_output=True, text=True).stdout.strip()


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. Wykrywanie zamiaru: URL, sciezka lokalna z .git, nowy projekt, brak repo.
    checks.append(("Wykrywa URL repozytorium w tresci zadania",
                   repo_workspace.wykryj(TASK_URL) ==
                   {"tryb": "clone", "zrodlo": "https://github.com/przyklad/strona.git"}))
    checks.append(("Wykrywa zamiar zalozenia nowego projektu",
                   repo_workspace.wykryj(TASK_INIT) == {"tryb": "init"}))
    checks.append(("Zadanie bez repozytorium -> None (subagent pracuje jak dotad)",
                   repo_workspace.wykryj({"title": "Napisz posta na LinkedIn"}) is None))
    checks.append(("Pole repo_url ma pierwszenstwo nad trescia",
                   repo_workspace.wykryj({"repo_url": "git@github.com:a/b.git",
                                          "title": "Zaloz nowy projekt"})["zrodlo"]
                   == "git@github.com:a/b.git"))

    # 2. Sciezka lokalna: katalog BEZ .git nie jest repozytorium (fail-closed).
    zwykly_katalog = Path(tempfile.mkdtemp())
    checks.append(("Katalog bez .git nie jest traktowany jako repozytorium",
                   repo_workspace.wykryj({"project_path": str(zwykly_katalog),
                                          "title": "Popraw kod"}) is None))

    # 3. Nazwa brancha wg konwencji <prefix>/<task_id>-<slug>.
    cfg = _konfiguracja(Path(tempfile.mkdtemp()))
    checks.append(("Branch zadania: prefiks + task_id + slug tytulu",
                   repo_workspace.nazwa_brancha({"task_id": "T-123", "title": "Popraw walidacje API"}, cfg)
                   == "agent/t-123-popraw-walidacje-api"))

    # 4. Nowy projekt: prawdziwy git init + pierwszy commit wg konwencji.
    korzen = Path(tempfile.mkdtemp())
    sandbox = repo_workspace.przygotuj(TASK_INIT, config=_konfiguracja(korzen))
    checks.append(("Nowy projekt: piaskownica przygotowana", bool(sandbox and sandbox.get("ok"))))
    checks.append(("Nowy projekt: pierwszy commit to '00 - pusty'",
                   _log(sandbox["path"]) == repo_workspace.PIERWSZY_COMMIT))
    checks.append(("Nowy projekt: jestesmy na branchu zadania, nie na galezi bazowej",
                   subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=sandbox["path"],
                                  capture_output=True, text=True).stdout.strip() == sandbox["branch"]))
    checks.append(("Nowy projekt: tozsamosc commitow ustawiona lokalnie (maszyna nie ma globalnej)",
                   subprocess.run(["git", "config", "user.name"], cwd=sandbox["path"],
                                  capture_output=True, text=True).stdout.strip() != ""))
    checks.append(("Nowy projekt: piaskownica lezy w sandbox_root, nie w repo bota",
                   str(korzen) in sandbox["path"]))

    # 5. Idempotencja: powtorzone wywolanie (retry zadania) wchodzi do tej samej
    # piaskownicy i tego samego brancha, nie zaklada nowej.
    sandbox_ponownie = repo_workspace.przygotuj(TASK_INIT, config=_konfiguracja(korzen))
    checks.append(("Retry zadania: ta sama piaskownica i ten sam branch",
                   sandbox_ponownie["path"] == sandbox["path"]
                   and sandbox_ponownie["branch"] == sandbox["branch"]))
    checks.append(("Retry zadania: historia nie zdublowana",
                   _log(sandbox["path"]) == repo_workspace.PIERWSZY_COMMIT))

    # 6. Nieudany klon -> ok=False z powodem (fail-closed, agentic_worker eskaluje).
    def _runner_klon_padl(cmd, **kwargs):
        if cmd[:2] == ["git", "clone"]:
            return _WynikRunnera(returncode=128, stderr="repository not found")
        return _WynikRunnera()

    wynik_klonu = repo_workspace.przygotuj(TASK_URL, config=_konfiguracja(Path(tempfile.mkdtemp())),
                                           runner=_runner_klon_padl)
    checks.append(("Nieudany klon -> ok=False", wynik_klonu.get("ok") is False))
    checks.append(("Nieudany klon -> powod niesie tresc bledu gita",
                   "repository not found" in wynik_klonu.get("powod", "")))

    # 7. new_projects_root: nowe projekty moga miec wlasny korzen poza runs/.
    projekty = Path(tempfile.mkdtemp()) / "projekty"
    folder = repo_workspace.folder_piaskownicy(TASK_INIT, {"tryb": "init"},
                                               _konfiguracja(korzen, new_projects_root=str(projekty)))
    checks.append(("new_projects_root: nowy projekt idzie do wlasnego korzenia",
                   str(projekty) in str(folder)))

    print("\n--- Wynik testu dymnego repo_workspace ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedl.")
        sys.exit(1)
    print("\nWszystkie testy przeszly.")


if __name__ == "__main__":
    run()
