"""
Prawdziwy subagent — gdy executor.py nie rozpoznaje wąskiego workera dla
zadania (i task_decomposer.py zdecydował NIE dzielić go dalej), tu zadanie
faktycznie się WYKONUJE: Claude Code z realnym Read/Write/Edit + Skill.

Zapis plików ZOSTAJE ograniczony do WŁASNEGO folderu zadania
(runs/agentic_tasks/<task_id>_<tytuł>/), folderu TEGO SAMEGO zadania na
SharePoint/OneDrive (Zadania-Agenta/<task_id>_..., gdy ONEDRIVE_TASKS_ROOT
skonfigurowany — patrz _onedrive_task_folder) oraz, dla zadań o repozytorium,
WŁASNEJ piaskownicy repo (runs/repos/<task_id>_..., patrz repo_workspace.py) —
nigdy do katalogu roboczego człowieka ani do reszty maszyny. Od
25.08.2026 (decyzja właściciela) subagent ma NATOMIAST swobodny dostęp do
internetu (WebFetch/WebSearch, bez allowlisty domen) — to jest INNA oś
ograniczeń niż zapis plików (potwierdzone: tool_registry.check_call dla
"agentic_task" i tak sprawdza tylko `task_id`, żadnego parametru typu `url`,
więc allowlista domen nie miała tu żadnego mechanizmu wymuszenia). Klikanie
po ekranie/UI (computer use) zostaje WYŁĄCZNIE dla browser_worker.py, który
ma własną, odrębną allowlistę i profile logowania — ten subagent jej nie
dostaje.

Plan (co i jak zrobić) dostarcza runner_loop.py z task_thinker.think() —
BEZ zmian w tamtej funkcji, jej rola zostaje "analiza/plan", nie "finalny
wynik". Plan jest sprawdzany przez bot_content_check.judge() PRZED
wykonaniem: subagent dostaje zielone światło tylko dla podejścia, które
faktycznie adresuje zadanie — zero zmarnowanego czasu/kosztu na złe podejście.

Kontekst promptu buduje agentic_prompt.py (wydzielone 02.09.2026, limit 300
linii na plik): kontekst firmy, projekt/etap, rodzeństwo podzadań i STANDARDY
z .claude/rules. Każdy blok jest fail-soft: błąd/brak danych pomija TEN blok,
nie blokuje wykonania.

PRACA W REPOZYTORIUM (decyzja właściciela 02.09.2026). Gdy zadanie wskazuje
repozytorium (URL/ścieżka w treści, pole repo_url/project_path) albo prosi o
projekt od zera, repo_workspace.py daje zadaniu WŁASNY KLON w runs/repos/ i
branch zadania, subagent dostaje `Bash` (pełny, żeby móc budować i uruchamiać
testy), a repo_publish.py po jego pracy commituje wg konwencji firmowej
("NN - opis po polsku"), pushuje branch i próbuje otworzyć PR. Gita nie woła
model: numeracja commitów liczona jest z historii repo, nie zgadywana.
Zadania bez repozytorium działają dokładnie jak dotąd, w folderze zadania.

Fail-closed: brak planu / plan niedopasowany / brak Claude Code / błąd
wykonania / brak pliku wyniku -> executed=False (albo "NIE WYKONANO"),
acceptance_notes = powód. runner_loop.py eskaluje wprost przy
execution_result["executed"] is False — nigdy cichy fałszywy sukces.
"""

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import agentic_prompt
import bot_content_check
import cost_estimator
import model_registry
import repo_publish
import repo_workspace
import task_thinker
import tool_registry

APP_DIR = Path(__file__).parent
WORKSPACE_DIR = APP_DIR / "runs" / "agentic_tasks"
RESULT_FILENAME = agentic_prompt.RESULT_FILENAME
OPIS_COMMITA_FILENAME = agentic_prompt.OPIS_COMMITA_FILENAME
AGENTIC_TIMEOUT_SECONDS = 600  # realna praca (pliki, komendy), nie krótki prompt

# "Skill" dopisane 25.08.2026 — bez niego subagent MIAŁ dostępne skille (Power
# BI/PBIP/DAX itd., globalne u właściciela), ale nie wolno mu było ich wywołać.
# "WebFetch WebSearch" dopisane 25.08.2026 (decyzja właściciela: swobodne
# czytanie/szukanie w internecie, bez allowlisty domen). "Bash" dopisane
# 02.09.2026 (decyzja właściciela): bez niego subagent nie mógł uruchomić
# NICZEGO — ani gita, ani testów, ani budowania projektu — mimo że prompt
# obiecywał mu "uruchamiaj co potrzebne do realizacji planu". Klikanie po UI
# (computer use) zostaje wyłącznie dla browser_worker.py, z jego własną
# allowlistą.
NARZEDZIA_SUBAGENTA = "Read Write Edit Bash Skill WebFetch WebSearch"

# Publikacja, po której praca NIE jest dostarczona — fail-closed, runner_loop
# eskaluje do człowieka (patrz repo_publish.zamknij). "brak_zmian" tu NIE jest:
# zadanie analityczne w repo może legalnie nie zmienić ani jednego pliku.
NIEUDANE_PUBLIKACJE = ("commit_odrzucony", "commit_nieudany")


def _slug(text, limit=60):
    """Kopia runner_loop._slug/task_decomposer... — nie importować, cykliczny
    import (runner_loop już importuje agentic_worker)."""
    slug = re.sub(r"[^\w\-]+", "_", text or "", flags=re.UNICODE).strip("_")
    return (slug[:limit] or "zadanie")


def _odmowa(powod, cost_usd=0.0):
    return {"cost_usd": cost_usd, "tool": "agentic_task", "executed": False,
            "acceptance_notes": powod, "output": {"refused": powod}}


def _nie_wykonano(powod, cost_usd=0.0, output=None):
    """executed=False (nie True) — zgodnie z kontraktem modułu (patrz docstring
    na górze pliku): błąd wykonania subagenta / brak pliku wyniku to awaria
    TOOLINGU (subprocess padł, albo nic nie zapisał), nie brak danych źródłowych
    (to inna kategoria niż np. integracje_worker._nie_wykonano dla "źródło nie
    ma odpowiedzi" — tam executed=True jest celowe). Realny bug 27.08.2026,
    znaleziony w audycie: executed=True tutaj wyłączało eskalację w
    runner_loop.py (`execution_result.get("executed") is False`), więc
    prawdziwe awarie subagenta mogły cicho zamykać się jako "done"."""
    return {"cost_usd": cost_usd, "tool": "agentic_task", "executed": False,
            "acceptance_notes": "NIE WYKONANO — " + powod, "output": output or {}}


def _onedrive_task_folder(task):
    """Folder OneDrive/SharePoint (biblioteka 'Wirtualny pracownik', root_folder
    'Zadania-Agenta' — config/sharepoint.yaml) TEGO zadania — decyzja właściciela
    29.08.2026: subagent ma mieć zapis TAKŻE tam, nie tylko we własnym lokalnym
    folderze roboczym (dziś jedyny wynik trafiał tam dopiero PO fakcie, przez
    output_decider.build_file w runner_loop._save_result_to_onedrive).

    Kopia logiki wyszukania/nazwania folderu z runner_loop._save_result_to_onedrive
    (NIE importować stamtąd — cykliczny import: runner_loop już importuje
    agentic_worker). Ten sam wzorzec duplikacji co _slug() w tym pliku.
    Idempotentne: jeśli runner_loop już utworzył ten folder wcześniej (albo
    utworzy go PÓŹNIEJ, po zakończeniu subagenta), oba trafiają w TEN SAM
    folder (dopasowanie po prefiksie task_id/parent_task_id).

    Fail-soft: brak ONEDRIVE_TASKS_ROOT / OneDrive niezsynchronizowane na tej
    maszynie -> None — subagent dostaje wtedy TYLKO swój lokalny folder roboczy,
    jak przed tą zmianą."""
    root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    if not root:
        return None
    root_path = Path(root)
    if not root_path.parent.exists():
        return None
    effective_id = task.get("parent_task_id") or task.get("task_id") or "zadanie"
    istniejace = sorted(root_path.glob(f"{effective_id}_*")) if root_path.exists() else []
    if istniejace:
        return istniejace[0]
    data = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    nowy_folder = root_path / f"{effective_id}_{data}_{_slug(task.get('title', ''))}"
    nowy_folder.mkdir(parents=True, exist_ok=True)
    return nowy_folder


def _opis_commita(folder, task):
    """Opis commitu napisany przez subagenta (plik opis-commita.txt, jedna
    linia). Brak pliku -> tytuł zadania: numer i tak dokłada repo_publish,
    więc commit zawsze spełnia konwencję, nawet gdy subagent opisu nie zostawi."""
    sciezka = folder / OPIS_COMMITA_FILENAME
    if sciezka.is_file():
        pierwsza_linia = sciezka.read_text(encoding="utf-8").strip().split("\n")[0].strip()
        if pierwsza_linia:
            return pierwsza_linia
    return task.get("title") or "zmiany agenta"


def _publikuj_zmiany(sandbox, task, folder):
    """Commit wg konwencji + push + PR. Nigdy nie rzuca: awaria publikacji jest
    zwracana jako akcja, o której decyduje wołający (fail-closed dla
    NIEUDANE_PUBLIKACJE)."""
    try:
        return repo_publish.zamknij(sandbox, _opis_commita(folder, task))
    except (OSError, subprocess.SubprocessError) as exc:
        return {"akcja": "commit_nieudany", "powod": f"publikacja zmian nie powiodła się: {exc}",
                "branch": sandbox.get("branch")}


def _uruchom_subagenta(claude_exe, model, prompt, katalog_pracy, dodatkowe_foldery, env):
    """Jedno wywołanie Claude Code headless. Zwraca (result, błąd_lub_None).

    Prompt zaraz po --model: --allowedTools i --add-dir są WARIADYCZNE
    (konsumują każdy kolejny token bez "-" na początku), więc prompt PO nich
    zostałby połknięty jako kolejny "katalog"/"tool" zamiast trafić do CLI jako
    właściwy prompt (znaleziony 24.08.2026 na żywym teście — CLI kończył się
    "Input must be provided...")."""
    try:
        result = subprocess.run(
            [claude_exe, "-p", "--model", model, prompt, "--permission-mode", "acceptEdits",
             "--allowedTools", NARZEDZIA_SUBAGENTA,
             "--add-dir", *dodatkowe_foldery],
            cwd=str(katalog_pracy),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=AGENTIC_TIMEOUT_SECONDS,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, f"Wykonanie przez subagenta nie powiodło się: {exc}"
    return result, None


def run(task, thinking, client=None, context=None):
    """Wykonuje zadanie przez prawdziwego subagenta. Zwraca execution_result
    (cost_usd, tool, executed, acceptance_notes, output, functional_checks).
    Nigdy nie rzuca — każda awaria degraduje do odmowy/"NIE WYKONANO".

    client: opcjonalny ProjectlyClient/MockProjectlyClient — używany TYLKO do
    dociągnięcia nazwy projektu do kontekstu promptu (project_name). Brak/błąd
    -> fail-soft, ten fragment kontekstu jest po prostu pomijany.

    context: kesz projektów/etapów/wiedzy z context_cache.py (decyzja
    właściciela 30.08.2026) — opcjonalny, odświeżany PRZEZ WOŁAJĄCEGO
    (runner_loop.py, raz na cykl), nie tutaj (subagent nie ma sam odpytywać
    Projectly o kesz przy każdym zadaniu)."""
    plan_text = thinking.get("reasoning") if thinking else None
    if not plan_text:
        return _odmowa("Brak planu (task_thinker.think niedostępny) — nie mogę bezpiecznie "
                       "wykonać zadania bez zweryfikowanego podejścia.")

    ocena_planu = bot_content_check.judge(task, plan_text, mode="plan", context=context)
    if not ocena_planu["aligned"]:
        return _odmowa(f"Plan nie odpowiada zadaniu: {ocena_planu['reasoning']}",
                       cost_usd=ocena_planu["cost_usd"])

    claude_exe = task_thinker._find_claude()
    if not claude_exe:
        return _odmowa("Brak Claude Code (claude login) — nie mogę wykonać zadania realnie.",
                       cost_usd=ocena_planu["cost_usd"])

    folder = WORKSPACE_DIR / f"{task.get('task_id') or 'zadanie'}_{_slug(task.get('title', ''))}"
    folder.mkdir(parents=True, exist_ok=True)

    kontrakt = tool_registry.check_call("agentic_task", {"task_id": task.get("task_id") or ""})
    if not kontrakt["allowed"]:
        return _odmowa(kontrakt["reason"], cost_usd=ocena_planu["cost_usd"])

    sandbox = repo_workspace.przygotuj(task)
    if sandbox and not sandbox.get("ok"):
        return _nie_wykonano("nie udało się przygotować repozytorium zadania: "
                             + str(sandbox.get("powod") or "nieznany powód"),
                             cost_usd=ocena_planu["cost_usd"])

    sharepoint_folder = _onedrive_task_folder(task)
    prompt = agentic_prompt.build(task, plan_text, folder, client,
                                  sharepoint_folder=sharepoint_folder, context=context,
                                  sandbox=sandbox)
    if prompt.startswith("-"):
        # Żywy incydent 25.08.2026: kontekst firmy (kontekst_firmy.zbuduj) zaczyna
        # się od "--- KONTEKST FIRMY ---", a CLI Claude Code parsuje pierwszy
        # token argv zaczynający się od "-" jako NIEZNANĄ OPCJĘ, nie jako treść
        # promptu ("error: unknown option ...") — subagent nigdy się nie
        # wykonywał, tylko odmawiał kodem 1. Spacja na początku nic nie zmienia
        # w tym, co czyta model, ale broni przed tym parsowaniem.
        prompt = " " + prompt
    _, model = model_registry.resolve("agentic_worker.run")
    # ANTHROPIC_API_KEY usuwany ze środowiska podprocesu z tego samego powodu
    # co w task_thinker._think_via_claude_code: obecność klucza wyłącza
    # connectory `claude login`, `claude -p` kończy się kodem 1.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    # --add-dir jest WARIADYCZNE (patrz komentarz niżej) — drugi katalog dopisany
    # do TEJ SAMEJ grupy argumentów, nie osobna flaga. Folder OneDrive/SharePoint
    # (decyzja właściciela 29.08.2026) dopisany TYLKO gdy faktycznie się rozwiązał
    # (fail-soft — patrz _onedrive_task_folder).
    # Katalog pracy: piaskownica repo, gdy zadanie dotyczy repozytorium, inaczej
    # folder zadania (jak dotąd). Folder zadania jest w --add-dir ZAWSZE, bo tam
    # i tak ląduje wynik.md czytany przez runner_loop/bramkę jakości.
    katalog_pracy = Path(sandbox["path"]) if sandbox else folder
    dodatkowe_foldery = ([str(folder)]
                         + ([sandbox["path"]] if sandbox else [])
                         + ([str(sharepoint_folder)] if sharepoint_folder else []))
    result, blad = _uruchom_subagenta(claude_exe, model, prompt, katalog_pracy,
                                      dodatkowe_foldery, env)
    if blad:
        return _odmowa(blad, cost_usd=ocena_planu["cost_usd"])

    cost_wykonania = cost_estimator.estimate_call("claude_code") + ocena_planu["cost_usd"]

    if result.returncode != 0:
        # stderr I stdout — niektóre błędy CLI (np. wyczerpane usage credits)
        # trafiają na stdout, nie stderr (ten sam wzorzec naprawiony 27.08.2026
        # w task_thinker.py i repo_auto_improver.py — bez tego prawdziwa
        # przyczyna awarii bywa całkowicie niewidoczna w logu).
        tresc_bledu = (result.stderr or "").strip() or (result.stdout or "").strip()
        return _nie_wykonano(f"subagent zwrócił kod {result.returncode}: {tresc_bledu[:300]}",
                             cost_usd=cost_wykonania)

    wynik_path = folder / RESULT_FILENAME
    if not wynik_path.exists() or not wynik_path.read_text(encoding="utf-8").strip():
        return _nie_wykonano(f"subagent zakończył się, ale nie zostawił pliku {RESULT_FILENAME} "
                             "z odpowiedzią.", cost_usd=cost_wykonania, output={"folder": str(folder)})

    tresc = wynik_path.read_text(encoding="utf-8").strip()
    publikacja = _publikuj_zmiany(sandbox, task, folder) if sandbox else None
    if publikacja and publikacja["akcja"] in NIEUDANE_PUBLIKACJE:
        return _nie_wykonano(repo_publish.opis_dla_czlowieka(publikacja),
                             cost_usd=cost_wykonania,
                             output={"folder": str(folder), "repo": publikacja})

    opis_repo = f"\n\nRepozytorium: {repo_publish.opis_dla_czlowieka(publikacja)}" if publikacja else ""
    return {
        "cost_usd": cost_wykonania,
        "tool": "agentic_task",
        "executed": True,
        "acceptance_notes": tresc + opis_repo,
        "source_note": f"Subagent Claude Code, Read/Write/Edit ograniczone do {folder.name}/"
                       + (f", piaskownica repo {sandbox['branch']}" if sandbox else "")
                       + (f" i folderu SharePoint/OneDrive {sharepoint_folder.name}/." if sharepoint_folder else "."),
        "output": {"folder": str(folder),
                   "sharepoint_folder": str(sharepoint_folder) if sharepoint_folder else None,
                   "repo": publikacja},
        "functional_checks": [{"name": f"Plik {RESULT_FILENAME} zapisany i niepusty",
                               "type": "nonempty_file", "target": str(wynik_path)}],
    }
