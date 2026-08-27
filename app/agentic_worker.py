"""
Prawdziwy subagent — gdy executor.py nie rozpoznaje wąskiego workera dla
zadania (i task_decomposer.py zdecydował NIE dzielić go dalej), tu zadanie
faktycznie się WYKONUJE: Claude Code z realnym Read/Write/Edit + Skill.

Zapis plików ZOSTAJE ograniczony do WŁASNEGO folderu zadania
(runs/agentic_tasks/<task_id>_<tytuł>/) — nigdy do reszty repo/maszyny. Od
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

Kontekst promptu (od 25.08.2026): kontekst firmy (kontekst_firmy.zbuduj —
ta sama funkcja co w task_brief_builder.py, wcześniej NIE podłączona tutaj),
nazwa projektu (client.project_name, gdy client podany) i — dla podzadań —
tytuły/statusy innych podzadań tego samego zadania głównego
(task["sibling_tasks"], ustawiane przez runner_loop.py). Każdy blok jest
fail-soft: błąd/brak danych pomija TEN blok, nie blokuje wykonania.

Fail-closed: brak planu / plan niedopasowany / brak Claude Code / błąd
wykonania / brak pliku wyniku -> executed=False (albo "NIE WYKONANO"),
acceptance_notes = powód. runner_loop.py eskaluje wprost przy
execution_result["executed"] is False — nigdy cichy fałszywy sukces.
"""

import os
import re
import subprocess
from pathlib import Path

import bot_content_check
import cost_estimator
import kontekst_firmy
import model_registry
import task_thinker
import tool_registry

APP_DIR = Path(__file__).parent
WORKSPACE_DIR = APP_DIR / "runs" / "agentic_tasks"
RESULT_FILENAME = "wynik.md"
AGENTIC_TIMEOUT_SECONDS = 600  # realna praca (pliki, komendy), nie krótki prompt


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


def _kontekst_firmy_blok(task):
    """Fail-soft: błąd/brak dopasowania -> pusty string, nie blokuje promptu."""
    tekst_zadania = " ".join(str(task.get(k) or "") for k in ("title", "description"))
    try:
        return kontekst_firmy.zbuduj(tekst_zadania)
    except Exception:  # noqa: BLE001 — kontekst jest dodatkiem, nie warunkiem wykonania
        return ""


def _kontekst_projektu_blok(task, client):
    """Fail-soft: brak client/project_id albo błąd -> pusty string."""
    if client is None or not task.get("project_id"):
        return ""
    try:
        nazwa = client.project_name(task["project_id"])
    except Exception:  # noqa: BLE001
        return ""
    return f"Projekt: {nazwa}" if nazwa else ""


def _kontekst_rodzenstwa_blok(task):
    """Inne podzadania tego samego zadania głównego — ustawiane przez
    runner_loop.py w task["sibling_tasks"]. Fail-soft: brak/puste -> ''."""
    rodzenstwo = task.get("sibling_tasks") or []
    if not rodzenstwo:
        return ""
    linie = "\n".join(
        f"- {s.get('title') or '?'} (status: {s.get('status') or '?'})" for s in rodzenstwo
    )
    return f"Inne podzadania tego samego zadania głównego:\n{linie}"


def _build_prompt(task, plan_text, folder, client=None):
    bloki_kontekstu = [
        blok for blok in (
            _kontekst_firmy_blok(task),
            _kontekst_projektu_blok(task, client),
            _kontekst_rodzenstwa_blok(task),
        )
        if blok
    ]
    kontekst = ("\n\n".join(bloki_kontekstu) + "\n\n") if bloki_kontekstu else ""
    return (
        kontekst +
        f"Zadanie: {task.get('title', '')}\n"
        f"Cel: {task.get('expected_result', '')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria', '')}\n"
        f"Opis: {(task.get('description') or '')[:2000]}\n\n"
        f"Zatwierdzony plan podejścia:\n{plan_text}\n\n"
        "Wykonaj to zadanie NAPRAWDĘ w bieżącym katalogu — czytaj/pisz pliki, "
        "szukaj i czytaj strony w internecie gdy to pomaga (masz do tego "
        "narzędzia), uruchamiaj co potrzebne do realizacji planu. Finalną, "
        f"czytelną dla człowieka odpowiedź zapisz w pliku '{RESULT_FILENAME}' "
        "(Markdown) w bieżącym katalogu — to ma być PEŁNE ROZWIĄZANIE zadania, "
        "nie opis planu ani streszczenie tego, co zamierzasz zrobić. WOLNO Ci "
        "wyłącznie MODYFIKOWAĆ/EDYTOWAĆ istniejące pliki i DODAWAĆ nowe — "
        "NIGDY nie usuwaj żadnego pliku (decyzja właściciela repozytorium)."
    )


def run(task, thinking, client=None):
    """Wykonuje zadanie przez prawdziwego subagenta. Zwraca execution_result
    (cost_usd, tool, executed, acceptance_notes, output, functional_checks).
    Nigdy nie rzuca — każda awaria degraduje do odmowy/"NIE WYKONANO".

    client: opcjonalny ProjectlyClient/MockProjectlyClient — używany TYLKO do
    dociągnięcia nazwy projektu do kontekstu promptu (project_name). Brak/błąd
    -> fail-soft, ten fragment kontekstu jest po prostu pomijany."""
    plan_text = thinking.get("reasoning") if thinking else None
    if not plan_text:
        return _odmowa("Brak planu (task_thinker.think niedostępny) — nie mogę bezpiecznie "
                       "wykonać zadania bez zweryfikowanego podejścia.")

    ocena_planu = bot_content_check.judge(task, plan_text, mode="plan")
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

    prompt = _build_prompt(task, plan_text, folder, client)
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
    try:
        result = subprocess.run(
            # Prompt zaraz po --model: --allowedTools i --add-dir są WARIADYCZNE
            # (konsumują każdy kolejny token bez "-" na początku), więc prompt
            # PO nich zostałby połknięty jako kolejny "katalog"/"tool" zamiast
            # trafić do CLI jako właściwy prompt (znaleziony 24.08.2026 na
            # żywym teście — CLI kończył się "Input must be provided...").
            # "Skill" dopisane 25.08.2026 — bez niego subagent MIAŁ dostępne
            # skille (Power BI/PBIP/DAX itd., globalne u właściciela), ale nie
            # wolno mu było ich wywołać (poza allowlistą), więc faktycznie
            # pracował bez nich mimo że istniały.
            # "WebFetch WebSearch" dopisane 25.08.2026 — decyzja właściciela:
            # subagent ma swobodny dostęp do internetu (czytanie/szukanie),
            # bez allowlisty domen. Klikanie po UI zostaje wyłącznie dla
            # browser_worker.py, który ma odrębną, ograniczoną allowlistę.
            [claude_exe, "-p", "--model", model, prompt, "--permission-mode", "acceptEdits",
             "--allowedTools", "Read Write Edit Skill WebFetch WebSearch", "--add-dir", str(folder)],
            cwd=str(folder),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=AGENTIC_TIMEOUT_SECONDS,
            env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return _odmowa(f"Wykonanie przez subagenta nie powiodło się: {exc}",
                       cost_usd=ocena_planu["cost_usd"])

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
    return {
        "cost_usd": cost_wykonania,
        "tool": "agentic_task",
        "executed": True,
        "acceptance_notes": tresc,
        "source_note": f"Subagent Claude Code, Read/Write/Edit ograniczone do {folder.name}/.",
        "output": {"folder": str(folder)},
        "functional_checks": [{"name": f"Plik {RESULT_FILENAME} zapisany i niepusty",
                               "type": "nonempty_file", "target": str(wynik_path)}],
    }
