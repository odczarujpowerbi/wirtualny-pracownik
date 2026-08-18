"""
Krok "myślenia" — bot analizuje zadanie realnym modelem, zanim (i zamiast)
tylko je sklasyfikuje. To pierwszy krok od zaślepki wykonania (runner_loop
execution_result) do faktycznej pracy: model dostaje treść zadania i zwraca
zwięzłą analizę (co rozumie, plan, ryzyka, rekomendacja), która ląduje w
komentarzu w Projectly.

Zgodnie z ustaleniem: główny model działa przez LOGOWANIE W TERMINALU
(Claude Code, `claude login`, subskrypcja) — wołamy `claude -p` (tryb
headless), NIE SDK z kluczem. Fallback na SDK anthropic tylko jeśli Claude
Code nie ma, a jest ANTHROPIC_API_KEY. Brak obu = degradacja bez wywalania
pętli (zwraca available=False, runner leci dalej na samej klasyfikacji).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env (ANTHROPIC_API_KEY fallback)

THINK_TIMEOUT_SECONDS = 120
MAX_FIELD_CHARS = 1500


def _find_claude():
    """Znajduje CLI 'claude' nawet gdy nie jest w PATH (natywny instalator kładzie
    je w ~/.local/bin, o czym bootstrap ostrzega przy braku wpisu w PATH)."""
    exe = shutil.which("claude")
    if exe:
        return exe
    for candidate in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if candidate.exists():
            return str(candidate)
    return None


def build_prompt(task):
    def trim(value):
        text = str(value) if value not in (None, "") else "(brak)"
        return text[:MAX_FIELD_CHARS]

    return (
        "Jesteś wirtualnym pracownikiem. Przeanalizuj zadanie i odpowiedz zwięźle "
        "(maks. 8 zdań), w punktach:\n"
        "1. Co rozumiesz, że trzeba zrobić.\n"
        "2. Proponowany plan/podejście (kroki).\n"
        "3. Ryzyka albo czego brakuje, żeby to wykonać.\n"
        "4. Rekomendacja: automatycznie czy potrzebna decyzja człowieka.\n\n"
        f"Tytuł: {trim(task.get('title'))}\n"
        f"Oczekiwany rezultat: {trim(task.get('expected_result'))}\n"
        f"Kryteria akceptacji: {trim(task.get('acceptance_criteria'))}\n"
        f"Opis: {trim(task.get('description'))}\n"
    )


def _think_via_claude_code(claude_exe, prompt):
    """Wywołuje Claude Code headless. cwd = katalog neutralny (temp), żeby CLI
    nie wciągało kontekstu tego repo. Subskrypcja -> koszt per-call nieraportowany."""
    result = subprocess.run(
        [claude_exe, "-p", prompt],
        cwd=tempfile.gettempdir(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=THINK_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return {"available": True, "ok": False, "reasoning": None,
                "detail": f"claude -p zwrócił kod {result.returncode}: {(result.stderr or '').strip()[:300]}",
                "cost_usd": 0.0, "source": "claude_code"}
    return {"available": True, "ok": True, "reasoning": (result.stdout or "").strip(),
            "detail": "OK", "cost_usd": 0.0, "source": "claude_code"}


def _think_via_sdk(prompt):
    """Fallback: SDK anthropic z ANTHROPIC_API_KEY (gdy brak Claude Code)."""
    try:
        import anthropic
    except ImportError:
        return None
    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    return {"available": True, "ok": True, "reasoning": text.strip(), "detail": "OK (SDK)",
            "cost_usd": 0.0, "source": "anthropic_sdk"}


def think(task):
    """Zwraca {available, ok, reasoning, detail, cost_usd, source}. Nigdy nie
    rzuca — błąd/timeout/brak modelu degraduje się do available/ok=False, żeby
    runner mógł dokończyć zadanie na samej klasyfikacji."""
    prompt = build_prompt(task)
    claude_exe = _find_claude()
    if claude_exe:
        try:
            return _think_via_claude_code(claude_exe, prompt)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"available": True, "ok": False, "reasoning": None,
                    "detail": f"Claude Code niedostępny/timeout: {exc}", "cost_usd": 0.0, "source": "claude_code"}

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            sdk_result = _think_via_sdk(prompt)
            if sdk_result:
                return sdk_result
        except Exception as exc:  # noqa: BLE001  # fallback nie może wywalić runnera
            return {"available": True, "ok": False, "reasoning": None,
                    "detail": f"SDK anthropic błąd: {exc}", "cost_usd": 0.0, "source": "anthropic_sdk"}

    return {"available": False, "ok": False, "reasoning": None,
            "detail": "Brak Claude Code (claude login) ani ANTHROPIC_API_KEY — pomijam myślenie.",
            "cost_usd": 0.0, "source": None}


if __name__ == "__main__":
    demo = {
        "title": "Sprawdź plik testowy INDEKA",
        "expected_result": "Potwierdzenie, że plik się otwiera i ma oczekiwane kolumny",
        "acceptance_criteria": "Plik otwarty bez błędu; kolumny zgodne z listą",
        "description": "Walidacja pliku źródłowego przed wczytaniem do raportu.",
    }
    print(think(demo))
