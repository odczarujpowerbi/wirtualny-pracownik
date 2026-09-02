"""
Publikacja pracy agenta w repozytorium: commit wg konwencji organizacyjnej,
push brancha, proba PR.

Powod: agent, ktory umie edytowac pliki, ale commituje "auto-fix: cos tam",
lamie standard organizacyjny z .claude/rules/git-workflow.md ("NN - opis po
polsku", numer dwucyfrowy, jeden logiczny krok = jeden commit). Numeracja nie
moze byc zgadywana przez model, bo model nie widzi historii repo, wiec liczy ja
TEN modul, z `git log`.

Podzial odpowiedzialnosci (swiadomy, ten sam wzorzec co w repo_auto_improver.py):
subagent PRACUJE na plikach, a gita wola kod, nie model. Model nie dostaje
`git commit` do reki, wiec nie moze przypadkiem zacommitowac na galezi bazowej,
nadpisac historii ani wypchnac sekretow.

Fail-closed przy sekretach: jesli w commicie znalazlby sie plik wygladajacy na
sekret (.env, secrets/, klucz prywatny), commit jest ODRZUCANY, nie "poprawiany".

Kolejne akcje zwracane przez zamknij():
  brak_zmian        -> subagent nic nie zmienil w repo,
  commit_odrzucony  -> zmiany zawieraly sekret, nic nie zostalo zapisane,
  commit_nieudany   -> git commit zwrocil blad,
  commit_lokalny    -> commit jest, push wylaczony w konfiguracji,
  branch_bez_push   -> commit jest, push sie nie udal (np. brak uprawnien),
  branch_bez_pr     -> branch wypchniety, PR nie powstal (brak gh / brak logowania),
  pr_utworzony      -> pelna sciezka: commit + push + PR.
"""

import shutil
import subprocess
from pathlib import Path

MAX_DLUGOSC_OPISU = 72
ILE_COMMITOW_WSTECZ = 50

# Wzorce plikow, ktorych agent nie zacommituje NIGDY (regula 9 z coding-rules.md).
WZORCE_SEKRETOW = (".env", "secrets/", "secrets\\", "id_rsa", ".pem", ".pfx",
                   "credentials.json", "token.json")

# Typowa lokalizacja GitHub CLI na Windowsie, gdy nie ma go w PATH biezacej sesji.
SCIEZKI_GH = (r"C:\Program Files\GitHub CLI\gh.exe",
              r"C:\Program Files (x86)\GitHub CLI\gh.exe")


def _run(cmd, cwd=None, timeout=120, runner=subprocess.run):
    """Jedyne miejsce wolajace git/gh w tym module (testy podmieniaja runner)."""
    return runner(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                  text=True, encoding="utf-8", timeout=timeout)


def _stdout(wynik):
    return (getattr(wynik, "stdout", "") or "").strip()


def _blad(wynik):
    return ((getattr(wynik, "stderr", "") or "") or _stdout(wynik)).strip()[:300]


def nastepny_numer(repo_dir, runner=subprocess.run):
    """Numer nastepnego commitu wg konwencji "NN - opis".

    Bierze NAJWYZSZY numer z ostatnich commitow, nie tylko z ostatniego: repo
    klienta moze miec commity bez numeracji wplecione miedzy nasze."""
    wynik = _run(["git", "log", f"-{ILE_COMMITOW_WSTECZ}", "--format=%s"],
                 cwd=repo_dir, timeout=30, runner=runner)
    numery = []
    for linia in _stdout(wynik).split("\n"):
        prefiks = linia.strip().split("-", 1)[0].strip()
        if prefiks.isdigit():
            numery.append(int(prefiks))
    return (max(numery) + 1) if numery else 1


def komunikat(repo_dir, opis, runner=subprocess.run):
    """"NN - opis po polsku", numer dwucyfrowy (git-workflow.md)."""
    czysty = " ".join(str(opis or "zmiany agenta").split())[:MAX_DLUGOSC_OPISU].strip()
    return f"{nastepny_numer(repo_dir, runner):02d} - {czysty or 'zmiany agenta'}"


def _zmienione_pliki(repo_dir, runner):
    wynik = _run(["git", "status", "--porcelain"], cwd=repo_dir, timeout=30, runner=runner)
    return [linia[3:].strip() for linia in _stdout(wynik).split("\n") if linia.strip()]


def znajdz_sekrety(pliki):
    """Pliki, ktorych nie wolno zacommitowac. Dopasowanie po fragmencie sciezki,
    zeby zlapac tez `app/secrets/.env` i `config/token.json`."""
    return [plik for plik in pliki
            if any(wzorzec in plik.lower() for wzorzec in WZORCE_SEKRETOW)]


def znajdz_gh():
    """gh z PATH albo ze standardowej instalacji Windows. None -> brak."""
    z_path = shutil.which("gh")
    if z_path:
        return z_path
    for sciezka in SCIEZKI_GH:
        if Path(sciezka).is_file():
            return sciezka
    return None


def _otworz_pr(sandbox, tytul, opis, runner):
    """Proba PR przez gh. Brak gh / brak logowania -> fail-soft z powodem, bo
    wypchniety branch to i tak dostarczona praca, tylko wymaga kliknieca."""
    gh = znajdz_gh()
    if not gh:
        return {"akcja": "branch_bez_pr",
                "powod": "brak GitHub CLI (gh) na tej maszynie, otworz PR recznie z brancha"}
    wynik = _run([gh, "pr", "create", "--base", sandbox["base_branch"],
                  "--head", sandbox["branch"], "--title", tytul,
                  "--body", opis or tytul],
                 cwd=sandbox["path"], timeout=120, runner=runner)
    if getattr(wynik, "returncode", 1) != 0:
        return {"akcja": "branch_bez_pr", "powod": f"gh pr create nie powiodl sie: {_blad(wynik)}"}
    return {"akcja": "pr_utworzony", "pr_url": _stdout(wynik).split("\n")[-1]}


def _commituj(sandbox, opis, runner):
    """Commit wg konwencji. Zwraca (ok, wynik_albo_komunikat)."""
    pliki = _zmienione_pliki(sandbox["path"], runner)
    if not pliki:
        return False, {"akcja": "brak_zmian", "powod": "subagent nie zmienil nic w repozytorium"}

    sekrety = znajdz_sekrety(pliki)
    if sekrety:
        return False, {"akcja": "commit_odrzucony",
                       "powod": f"zmiany zawieraja pliki wygladajace na sekrety: {', '.join(sekrety[:5])}"}

    tresc = komunikat(sandbox["path"], opis, runner)
    _run(["git", "add", "-A"], cwd=sandbox["path"], timeout=60, runner=runner)
    wynik = _run(["git", "commit", "-m", tresc], cwd=sandbox["path"], timeout=60, runner=runner)
    if getattr(wynik, "returncode", 1) != 0:
        return False, {"akcja": "commit_nieudany", "powod": f"git commit: {_blad(wynik)}"}
    return True, tresc


def zamknij(sandbox, opis, runner=subprocess.run):
    """Zamyka prace w piaskownicy: commit -> push -> PR. Nigdy nie rzuca.

    sandbox: wynik repo_workspace.przygotuj() z ok=True (path, branch,
    base_branch, config). Zwraca dict z kluczem `akcja` (lista w docstringu
    modulu) plus `commit`, `branch`, `pr_url`, `powod` gdy dotycza."""
    if not sandbox or not sandbox.get("ok"):
        return {"akcja": "brak_zmian", "powod": "brak piaskownicy repozytorium"}

    config = sandbox.get("config") or {}
    ok, wynik_commitu = _commituj(sandbox, opis, runner)
    if not ok:
        return {"branch": sandbox["branch"], **wynik_commitu}

    wspolne = {"branch": sandbox["branch"], "commit": wynik_commitu}
    if not config.get("push", True):
        return {"akcja": "commit_lokalny", **wspolne}

    push = _run(["git", "push", "-u", "origin", sandbox["branch"]], cwd=sandbox["path"],
                timeout=config.get("push_timeout_seconds", 180), runner=runner)
    if getattr(push, "returncode", 1) != 0:
        return {"akcja": "branch_bez_push", "powod": f"git push: {_blad(push)}", **wspolne}

    if not config.get("pull_request", True):
        return {"akcja": "branch_bez_pr", "powod": "PR wylaczony w config/repos.yaml", **wspolne}

    pr = _otworz_pr(sandbox, wynik_commitu, opis, runner)
    return {**pr, **wspolne} if pr["akcja"] == "pr_utworzony" else {**wspolne, **pr}


def opis_dla_czlowieka(wynik):
    """Jedno zdanie do komentarza w Projectly / notatki akceptacyjnej."""
    akcja = wynik.get("akcja")
    if akcja == "pr_utworzony":
        return f"Commit \"{wynik['commit']}\" na branchu {wynik['branch']}, PR: {wynik.get('pr_url', '?')}"
    if akcja == "branch_bez_pr":
        return (f"Commit \"{wynik['commit']}\" wypchniety na branch {wynik['branch']}, "
                f"PR do otwarcia recznie ({wynik.get('powod', '?')})")
    if akcja == "commit_lokalny":
        return f"Commit \"{wynik['commit']}\" lokalnie na branchu {wynik['branch']} (push wylaczony)"
    if akcja == "branch_bez_push":
        return f"Commit \"{wynik['commit']}\" powstal, ale push sie nie udal: {wynik.get('powod', '?')}"
    if akcja == "commit_odrzucony":
        return f"Zmiany NIE zostaly zacommitowane: {wynik.get('powod', '?')}"
    if akcja == "commit_nieudany":
        return f"Commit sie nie udal: {wynik.get('powod', '?')}"
    return f"Bez zmian w repozytorium ({wynik.get('powod', 'brak powodu')})"
