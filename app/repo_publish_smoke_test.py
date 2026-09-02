"""
Test dymny repo_publish.py. Commit/numeracja sprawdzane na PRAWDZIWYM gicie w
katalogu tymczasowym (bez zdalnego repo), push i PR na podmienionym runnerze
(zero sieci, zadne prawdziwe origin ani gh nie jest wolane).

Uzycie:
    python repo_publish_smoke_test.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

import repo_publish

BRANCH = "agent/t-test-zmiany"


class _WynikRunnera:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _repo_testowe():
    """Prawdziwe, puste repozytorium lokalne z jednym commitem "00 - pusty"."""
    katalog = Path(tempfile.mkdtemp()) / "repo"
    katalog.mkdir(parents=True)
    for cmd in (["git", "init", "-b", "main"],
                ["git", "config", "user.name", "Test"],
                ["git", "config", "user.email", "test@example.com"]):
        subprocess.run(cmd, cwd=str(katalog), capture_output=True, text=True, check=True)
    (katalog / ".gitkeep").touch()
    subprocess.run(["git", "add", "-A"], cwd=str(katalog), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "00 - pusty"], cwd=str(katalog),
                   capture_output=True, check=True)
    subprocess.run(["git", "checkout", "-b", BRANCH], cwd=str(katalog), capture_output=True)
    return katalog


def _sandbox(katalog, **config):
    return {"ok": True, "path": str(katalog), "branch": BRANCH, "base_branch": "main",
            "config": {"push": False, "pull_request": False, **config}}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. Numeracja commitow liczona z historii repo, nie zgadywana przez model.
    katalog = _repo_testowe()
    checks.append(("Numer po commicie '00 - pusty' to 1",
                   repo_publish.nastepny_numer(katalog) == 1))
    checks.append(("Komunikat commitu ma format 'NN - opis'",
                   repo_publish.komunikat(katalog, "dodano walidacje") == "01 - dodano walidacje"))

    # 2. Commit lokalny (push wylaczony) i rosnaca numeracja.
    (katalog / "index.html").write_text("<h1>test</h1>", encoding="utf-8")
    pierwszy = repo_publish.zamknij(_sandbox(katalog), "dodano szkielet strony")
    checks.append(("Push wylaczony -> akcja commit_lokalny", pierwszy["akcja"] == "commit_lokalny"))
    checks.append(("Commit wg konwencji", pierwszy["commit"] == "01 - dodano szkielet strony"))

    (katalog / "style.css").write_text("body{}", encoding="utf-8")
    drugi = repo_publish.zamknij(_sandbox(katalog), "dodano arkusz stylow")
    checks.append(("Kolejny commit ma numer 02", drugi["commit"] == "02 - dodano arkusz stylow"))

    # 3. Brak zmian: nie udajemy commitu.
    checks.append(("Brak zmian w repo -> akcja brak_zmian",
                   repo_publish.zamknij(_sandbox(katalog), "nic")["akcja"] == "brak_zmian"))

    # 4. Sekrety: commit ODRZUCONY, nie "poprawiony" (fail-closed, regula 9).
    (katalog / ".env").write_text("KEY=abc", encoding="utf-8")
    odrzucony = repo_publish.zamknij(_sandbox(katalog), "dodano konfiguracje")
    checks.append(("Sekret w zmianach -> akcja commit_odrzucony",
                   odrzucony["akcja"] == "commit_odrzucony"))
    checks.append(("Sekret w zmianach -> nazwa pliku w powodzie", ".env" in odrzucony["powod"]))
    checks.append(("Sekret w zmianach -> historia repo NIE zmieniona",
                   repo_publish.nastepny_numer(katalog) == 3))
    (katalog / ".env").unlink()
    checks.append(("znajdz_sekrety lapie tez sciezki zagniezdzone",
                   repo_publish.znajdz_sekrety(["app/secrets/.env", "src/main.py"])
                   == ["app/secrets/.env"]))

    # 5. Nieudany push -> commit zostaje, akcja mowi prawde (brak cichego sukcesu).
    (katalog / "README.md").write_text("# test", encoding="utf-8")

    def _runner_push_padl(cmd, **kwargs):
        if cmd[:2] == ["git", "push"]:
            return _WynikRunnera(returncode=128, stderr="Could not read from remote repository")
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              cwd=kwargs.get("cwd"), timeout=kwargs.get("timeout"))

    bez_pusha = repo_publish.zamknij(_sandbox(katalog, push=True), "dodano readme",
                                     runner=_runner_push_padl)
    checks.append(("Nieudany push -> akcja branch_bez_push", bez_pusha["akcja"] == "branch_bez_push"))
    checks.append(("Nieudany push -> commit jednak powstal",
                   bez_pusha["commit"] == "03 - dodano readme"))

    # 6. Pelna sciezka do PR: push OK i gh dostepny.
    (katalog / "CHANGELOG.md").write_text("# zmiany", encoding="utf-8")
    original_znajdz_gh = repo_publish.znajdz_gh
    wolane = {"gh": []}

    def _runner_wszystko_ok(cmd, **kwargs):
        if Path(str(cmd[0])).name.startswith("gh"):
            wolane["gh"] = cmd
            return _WynikRunnera(stdout="https://github.com/przyklad/repo/pull/4\n")
        if cmd[:2] == ["git", "push"]:
            return _WynikRunnera()
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              cwd=kwargs.get("cwd"), timeout=kwargs.get("timeout"))

    try:
        repo_publish.znajdz_gh = lambda: "gh"
        z_prem = repo_publish.zamknij(_sandbox(katalog, push=True, pull_request=True),
                                      "dodano changelog", runner=_runner_wszystko_ok)
    finally:
        repo_publish.znajdz_gh = original_znajdz_gh

    checks.append(("Push OK + gh -> akcja pr_utworzony", z_prem["akcja"] == "pr_utworzony"))
    checks.append(("PR: link zwrocony w wyniku", "pull/4" in z_prem["pr_url"]))
    checks.append(("PR: baza z galezi bazowej repo, head z brancha zadania",
                   "--base" in wolane["gh"] and wolane["gh"][wolane["gh"].index("--base") + 1] == "main"
                   and wolane["gh"][wolane["gh"].index("--head") + 1] == BRANCH))

    # 7. Brak gh -> fail-soft: branch wypchniety, PR do otwarcia recznie.
    (katalog / "LICENSE").write_text("MIT", encoding="utf-8")
    try:
        repo_publish.znajdz_gh = lambda: None
        bez_pr = repo_publish.zamknij(_sandbox(katalog, push=True, pull_request=True),
                                      "dodano licencje", runner=_runner_wszystko_ok)
    finally:
        repo_publish.znajdz_gh = original_znajdz_gh
    checks.append(("Brak gh -> akcja branch_bez_pr", bez_pr["akcja"] == "branch_bez_pr"))
    checks.append(("Brak gh -> commit i branch nadal w wyniku",
                   bez_pr["commit"] == "05 - dodano licencje" and bez_pr["branch"] == BRANCH))

    # 8. Opis dla czlowieka mowi, co sie realnie stalo.
    checks.append(("Opis dla czlowieka: PR z linkiem",
                   "pull/4" in repo_publish.opis_dla_czlowieka(z_prem)))
    checks.append(("Opis dla czlowieka: odrzucenie mowi wprost, ze nie zacommitowano",
                   "NIE zostaly zacommitowane" in repo_publish.opis_dla_czlowieka(odrzucony)))

    # 9. Brak piaskownicy -> nie wolamy gita w ogole.
    checks.append(("Brak piaskownicy -> brak_zmian, bez wolania gita",
                   repo_publish.zamknij(None, "cokolwiek")["akcja"] == "brak_zmian"))

    print("\n--- Wynik testu dymnego repo_publish ---")
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
