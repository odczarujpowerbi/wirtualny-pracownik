"""
Prawdziwy subagent — gdy executor.py nie rozpoznaje wąskiego workera dla
zadania (i task_decomposer.py zdecydował NIE dzielić go dalej), tu zadanie
faktycznie się WYKONUJE: Claude Code z realnym Read/Write/Edit, ograniczony
do WŁASNEGO folderu zadania (runs/agentic_tasks/<task_id>_<tytuł>/) — nigdy
do reszty repo/maszyny.

Plan (co i jak zrobić) dostarcza runner_loop.py z task_thinker.think() —
BEZ zmian w tamtej funkcji, jej rola zostaje "analiza/plan", nie "finalny
wynik". Plan jest sprawdzany przez bot_content_check.judge() PRZED
wykonaniem: subagent dostaje zielone światło tylko dla podejścia, które
faktycznie adresuje zadanie — zero zmarnowanego czasu/kosztu na złe podejście.

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
    return {"cost_usd": cost_usd, "tool": "agentic_task", "executed": True,
            "acceptance_notes": "NIE WYKONANO — " + powod, "output": output or {}}


def _build_prompt(task, plan_text, folder):
    return (
        f"Zadanie: {task.get('title', '')}\n"
        f"Cel: {task.get('expected_result', '')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria', '')}\n"
        f"Opis: {(task.get('description') or '')[:2000]}\n\n"
        f"Zatwierdzony plan podejścia:\n{plan_text}\n\n"
        "Wykonaj to zadanie NAPRAWDĘ w bieżącym katalogu — czytaj/pisz pliki, "
        "uruchamiaj co potrzebne do realizacji planu. Finalną, czytelną dla "
        f"człowieka odpowiedź zapisz w pliku '{RESULT_FILENAME}' (Markdown) w "
        "bieżącym katalogu — to ma być PEŁNE ROZWIĄZANIE zadania, nie opis "
        "planu ani streszczenie tego, co zamierzasz zrobić."
    )


def run(task, thinking):
    """Wykonuje zadanie przez prawdziwego subagenta. Zwraca execution_result
    (cost_usd, tool, executed, acceptance_notes, output, functional_checks).
    Nigdy nie rzuca — każda awaria degraduje do odmowy/"NIE WYKONANO"."""
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

    prompt = _build_prompt(task, plan_text, folder)
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
            [claude_exe, "-p", "--model", model, prompt, "--permission-mode", "acceptEdits",
             "--allowedTools", "Read Write Edit", "--add-dir", str(folder)],
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
        return _nie_wykonano(f"subagent zwrócił kod {result.returncode}: "
                             f"{(result.stderr or '').strip()[:300]}",
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
