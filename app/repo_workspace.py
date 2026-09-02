"""
Piaskownica repozytorium dla zadania agenta.

Powod: subagent (agentic_worker.py) startowal w PUSTYM folderze zadania i mial
tylko Read/Write/Edit, wiec zadanie "popraw kod w repo X" albo "zbuduj projekt"
bylo technicznie niewykonalne, nie tylko niedopracowane. Ten modul daje zadaniu
WLASNY klon repozytorium, poza katalogiem roboczym czlowieka.

Decyzja wlasciciela (02.09.2026): KLON PER ZADANIE, nigdy worktree zywego repo
i nigdy katalog roboczy uzytkownika. Dzieki temu:
  - niezacommitowane zmiany czlowieka nie koliduja z praca agenta,
  - `git pull` schedulera (repo_updater.py) nie wchodzi agentowi w droge,
  - po zadaniu zostaje sciezka do audytu (runs/ jest w .gitignore).

WAZNE, dlaczego nie "po prostu Bash w folderze zadania": folder zadania
(app/runs/agentic_tasks/...) lezy WEWNATRZ working tree wirtualnego pracownika,
wiec `git commit` w tym cwd zacommitowalby repo bota. Piaskownica jest osobnym
klonem poza tym drzewem.

Skad wiadomo, o ktore repo chodzi (wykryj):
  1. jawne pole zadania `repo_url` albo `project_path`,
  2. URL repozytorium w tresci zadania (https://... / git@...),
  3. lokalna sciezka z .git w tresci zadania,
  4. slowa o zalozeniu projektu od zera -> `git init` + commit "00 - pusty".
Brak ktoregokolwiek sygnalu -> None, czyli zadanie nie dotyczy repozytorium i
subagent pracuje jak dotad, w swoim folderze zadania.

Commit/push/PR NIE sa tutaj, sa w repo_publish.py (osobna odpowiedzialnosc: ten
modul przygotowuje miejsce pracy, tamten publikuje wynik).
"""

import subprocess
from pathlib import Path

import yaml

APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "config" / "repos.yaml"

DOMYSLNE = {
    "sandbox_root": "runs/repos",
    "base_branch": "main",
    "branch_prefix": "agent",
    "push": True,
    "pull_request": True,
    "new_projects_root": None,
    "commit_author_name": "Wirtualny pracownik (agent)",
    "commit_author_email": "kontakt@clickless.pl",
    "clone_timeout_seconds": 300,
    "push_timeout_seconds": 180,
}

# Slowa, po ktorych zakladamy NOWE repozytorium. Jednoznaczne z rozmyslu: samo
# "projekt" wystepuje w polowie zadan i zakladaloby repo bez potrzeby.
SLOWA_NOWY_PROJEKT = ("nowe repozytorium", "nowy projekt", "zainicjuj repozytorium",
                      "zaloz repozytorium", "zaloz projekt", "utworz projekt",
                      "stworz projekt", "git init", "projekt od zera")
PLIK_STARTOWY = ".gitkeep"
PIERWSZY_COMMIT = "00 - pusty"
POLA_TEKSTOWE = ("title", "description", "expected_result", "acceptance_criteria")
ZNAKI_OTOCZENIA = "\"'()[]<>,;:."


def load_config(path=CONFIG_PATH):
    """Konfiguracja pracy z repo, z domyslnymi wartosciami pod spodem."""
    try:
        dane = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except OSError:
        return dict(DOMYSLNE)
    return {**DOMYSLNE, **(dane.get("repo_work") or {})}


def _run(cmd, cwd=None, timeout=120, runner=subprocess.run):
    """Jedyne miejsce wolajace git w tym module, zeby test dymny mogl podmienic
    `runner` i nie dotykac zadnego prawdziwego repozytorium."""
    return runner(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                  text=True, encoding="utf-8", timeout=timeout)


def _slug(text, limit=40):
    """Bez wyrazen regularnych, zeby dzialalo tez na polskich znakach."""
    czyste = "".join(znak if znak.isalnum() else "-" for znak in (text or ""))
    while "--" in czyste:
        czyste = czyste.replace("--", "-")
    return czyste.strip("-").lower()[:limit] or "zadanie"


def _tokeny(tekst):
    """Tokeny tresci zadania, oczyszczone z cudzyslowow i interpunkcji. Sciezki
    ze spacjami nie sa wykrywane (swiadomie): w takim wypadku zadanie ma podac
    repozytorium w polu `repo_url`/`project_path`."""
    for token in (tekst or "").split():
        yield token.strip(ZNAKI_OTOCZENIA)


def _wyglada_na_url_repo(token):
    if token.startswith("git@"):
        return True
    return token.startswith("https://") and (token.endswith(".git") or "github.com" in token)


def _repo_lokalne(token):
    """Sciezka lokalna, ktora JEST repozytorium git (ma .git), albo None."""
    if not token:
        return None
    try:
        sciezka = Path(token)
        if sciezka.is_dir() and (sciezka / ".git").exists():
            return str(sciezka.resolve())
    except (OSError, ValueError):
        return None
    return None


def wykryj(task):
    """Zamiar zadania wobec repozytorium albo None, gdy zadanie go nie dotyczy.

    Zwraca {"tryb": "clone", "zrodlo": url_albo_sciezka} albo {"tryb": "init"}."""
    task = task or {}
    jawne = str(task.get("repo_url") or "").strip()
    if jawne:
        return {"tryb": "clone", "zrodlo": jawne}
    z_pola = _repo_lokalne(str(task.get("project_path") or "").strip())
    if z_pola:
        return {"tryb": "clone", "zrodlo": z_pola}

    tekst = " ".join(str(task.get(pole) or "") for pole in POLA_TEKSTOWE)
    for token in _tokeny(tekst):
        if _wyglada_na_url_repo(token):
            return {"tryb": "clone", "zrodlo": token}
    for token in _tokeny(tekst):
        lokalne = _repo_lokalne(token)
        if lokalne:
            return {"tryb": "clone", "zrodlo": lokalne}
    if any(slowo in tekst.lower() for slowo in SLOWA_NOWY_PROJEKT):
        return {"tryb": "init"}
    return None


def nazwa_brancha(task, config):
    """<prefix>/<task_id>-<slug tytulu>, np. agent/T-123-popraw-walidacje."""
    task_id = _slug(str((task or {}).get("task_id") or "zadanie"), limit=20)
    return f"{config['branch_prefix']}/{task_id}-{_slug((task or {}).get('title'))}"


def folder_piaskownicy(task, zamiar, config):
    """Katalog klonu/projektu TEGO zadania. Nowe projekty moga miec wlasny
    korzen (new_projects_root), zeby nie ginely w runs/ razem ze stanem."""
    nazwa = f"{(task or {}).get('task_id') or 'zadanie'}_{_slug((task or {}).get('title'))}"
    if zamiar["tryb"] == "init" and config.get("new_projects_root"):
        return Path(config["new_projects_root"]) / nazwa
    korzen = Path(config["sandbox_root"])
    if not korzen.is_absolute():
        korzen = APP_DIR / korzen
    return korzen / nazwa


def _ustaw_tozsamosc(repo_dir, config, runner):
    """Bez tego `git commit` w swiezym klonie failuje: ta maszyna NIE ma
    globalnego git user.name (sprawdzone 02.09.2026, tozsamosc jest ustawiona
    tylko lokalnie w repo wirtualnego pracownika)."""
    _run(["git", "config", "user.name", config["commit_author_name"]], cwd=repo_dir, runner=runner)
    _run(["git", "config", "user.email", config["commit_author_email"]], cwd=repo_dir, runner=runner)


def _galaz_biezaca(repo_dir, config, runner):
    """Realna galaz HEAD klonu (baza PR). Domyslna z configu jest tylko awaryjna:
    repozytorium klienta moze miec master/develop, nie main."""
    wynik = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_dir, runner=runner)
    nazwa = (getattr(wynik, "stdout", "") or "").strip()
    return nazwa if nazwa and nazwa != "HEAD" else config["base_branch"]


def _blad(wynik, domyslny):
    tresc = (getattr(wynik, "stderr", "") or getattr(wynik, "stdout", "") or "").strip()
    return f"{domyslny}: {tresc[:300]}" if tresc else domyslny


def _klonuj(zrodlo, docelowy, config, runner):
    docelowy.parent.mkdir(parents=True, exist_ok=True)
    wynik = _run(["git", "clone", zrodlo, str(docelowy)],
                 timeout=config["clone_timeout_seconds"], runner=runner)
    if getattr(wynik, "returncode", 1) != 0:
        return {"ok": False, "powod": _blad(wynik, "git clone nie powiodl sie")}
    return {"ok": True}


def _zainicjuj(docelowy, config, runner):
    """Nowy projekt od zera, od razu z pierwszym commitem wg konwencji
    organizacyjnej (.claude/rules/git-workflow.md: "00 - pusty")."""
    docelowy.mkdir(parents=True, exist_ok=True)
    wynik = _run(["git", "init", "-b", config["base_branch"]], cwd=docelowy, runner=runner)
    if getattr(wynik, "returncode", 1) != 0:
        return {"ok": False, "powod": _blad(wynik, "git init nie powiodl sie")}
    _ustaw_tozsamosc(docelowy, config, runner)
    (docelowy / PLIK_STARTOWY).touch()
    _run(["git", "add", PLIK_STARTOWY], cwd=docelowy, runner=runner)
    _run(["git", "commit", "-m", PIERWSZY_COMMIT], cwd=docelowy, runner=runner)
    return {"ok": True}


def _przelacz_na_branch(docelowy, branch, runner):
    """Branch zadania: istniejacy (retry tego samego zadania) -> checkout,
    nowy -> checkout -b. Zawsze branch, NIGDY praca wprost na galezi bazowej
    (CLAUDE.md: zmiany w kodzie ida branchem i PR-em)."""
    istnieje = _run(["git", "rev-parse", "--verify", branch], cwd=docelowy, runner=runner)
    if getattr(istnieje, "returncode", 1) == 0:
        return {"ok": True}
    wynik = _run(["git", "checkout", "-b", branch], cwd=docelowy, runner=runner)
    if getattr(wynik, "returncode", 1) != 0:
        return {"ok": False, "powod": _blad(wynik, f"nie udalo sie utworzyc brancha {branch}")}
    return {"ok": True}


def przygotuj(task, config=None, runner=subprocess.run):
    """Przygotowuje piaskownice repo dla zadania. Nigdy nie rzuca.

    None            -> zadanie nie dotyczy repozytorium (subagent pracuje jak dotad),
    {"ok": False}   -> repozytorium wykryte, ale przygotowanie sie nie udalo (powod),
    {"ok": True}    -> path/branch/base_branch gotowe do pracy subagenta.

    Idempotentne: powtorzone wywolanie dla tego samego zadania (retry) wchodzi
    do istniejacej piaskownicy zamiast klonowac od nowa."""
    zamiar = wykryj(task)
    if not zamiar:
        return None
    cfg = config or load_config()
    docelowy = folder_piaskownicy(task, zamiar, cfg)
    branch = nazwa_brancha(task, cfg)

    if not (docelowy / ".git").exists():
        przygotowanie = (_klonuj(zamiar["zrodlo"], docelowy, cfg, runner)
                         if zamiar["tryb"] == "clone" else _zainicjuj(docelowy, cfg, runner))
        if not przygotowanie["ok"]:
            return {**zamiar, **przygotowanie, "path": str(docelowy), "branch": branch}

    _ustaw_tozsamosc(docelowy, cfg, runner)
    base_branch = _galaz_biezaca(docelowy, cfg, runner)
    przelaczenie = _przelacz_na_branch(docelowy, branch, runner)
    if not przelaczenie["ok"]:
        return {**zamiar, **przelaczenie, "path": str(docelowy), "branch": branch}

    return {"ok": True, "tryb": zamiar["tryb"], "zrodlo": zamiar.get("zrodlo"),
            "path": str(docelowy), "branch": branch, "base_branch": base_branch,
            "config": cfg}
