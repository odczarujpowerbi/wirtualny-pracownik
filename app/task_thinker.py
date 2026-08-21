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

import json
import os
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env (ANTHROPIC_API_KEY fallback)
import cost_estimator
import model_registry
import task_brief_builder

THINK_TIMEOUT_SECONDS = 120

APP_DIR = Path(__file__).parent
# Katalogi, w których wolno uruchomić decydenta z KONTEKSTEM repo (Claude Code
# czyta wtedy pliki zadania). Spójne z allowed_roots kontraktów — poza nimi
# uruchamiamy w katalogu neutralnym (temp), żeby nie wciągać cudzego kontekstu.
_SAFE_CWD_ROOTS = [(APP_DIR / r).resolve() for r in ("workspace", "mock_data")]

# Lokalny model tekstowy (Ollama) jako ostatni fallback wołania modelu —
# używany przez ask_model() (np. Bożena, gdy nie ma ani Claude Code, ani klucza).
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_TEXT_MODEL = os.environ.get("OLLAMA_TEXT_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = 20


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
    """Prompt kroku myślenia = instrukcja + brief z pełnym kontekstem zadania
    (pola + oś czasu z trwałej historii). Kontekst decydenta rekonstruowany z
    state_store, nie z pamięci procesu (task_brief_builder)."""
    return task_brief_builder.build_thinking_prompt(task)


def _safe_cwd(task):
    """Katalog uruchomienia decydenta: repozytorium zadania (żeby model CZYTAŁ
    pliki zadania), gdy project_path jest istniejącym katalogiem w bezpiecznym
    korzeniu; inaczej katalog neutralny (temp)."""
    raw = task.get("project_path") if isinstance(task, dict) else None
    if raw:
        candidate = Path(raw).resolve()
        if candidate.is_dir() and any(candidate == r or r in candidate.parents for r in _SAFE_CWD_ROOTS):
            return str(candidate)
    return tempfile.gettempdir()


def _think_via_claude_code(claude_exe, prompt, caller, cwd=None):
    """Wywołuje Claude Code headless. `caller` identyfikuje wywołanie w tabeli
    config/model_tiers.yaml (np. "task_thinker.think", "web_answer.answer") —
    stąd bierzemy poziom (high/low) i konkretny model (model_registry.resolve).
    cwd = repo zadania (kontekst) albo temp. Koszt subskrypcji szacowany proxy
    (cost_estimator), żeby kill switch liczył wolumen wywołań."""
    role, model = model_registry.resolve(caller)
    cost = cost_estimator.estimate_call("claude_code")
    result = subprocess.run(
        [claude_exe, "-p", "--model", model, prompt],
        cwd=cwd or tempfile.gettempdir(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=THINK_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return {"available": True, "ok": False, "reasoning": None,
                "detail": f"claude -p zwrócił kod {result.returncode}: {(result.stderr or '').strip()[:300]}",
                "cost_usd": cost, "source": "claude_code", "model": model}
    return {"available": True, "ok": True, "reasoning": (result.stdout or "").strip(),
            "detail": "OK", "cost_usd": cost, "source": "claude_code", "model": model}


def _think_via_sdk(prompt, caller):
    """Fallback: SDK anthropic z ANTHROPIC_API_KEY (gdy brak Claude Code).
    `caller` -> model przez model_registry.resolve, tak jak w ścieżce CLI."""
    try:
        import anthropic
    except ImportError:
        return None
    role, model = model_registry.resolve(caller)
    client = anthropic.Anthropic()
    message = client.messages.create(
        model=model,
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "".join(block.text for block in message.content if getattr(block, "type", None) == "text")
    cost = cost_estimator.estimate_call("anthropic_sdk", input_chars=len(prompt), output_chars=len(text), role=role)
    return {"available": True, "ok": True, "reasoning": text.strip(), "detail": "OK (SDK)",
            "cost_usd": cost, "source": "anthropic_sdk", "model": model}


def _ask_ollama_text(prompt):
    """Lokalny model tekstowy przez Ollamę. Zwraca tekst albo None, gdy
    niedostępny — brak lokalnego modelu to nie błąd, tylko brak tej ścieżki."""
    payload = json.dumps({"model": OLLAMA_TEXT_MODEL, "prompt": prompt, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    text = (result.get("response") or "").strip()
    return text or None


def ask_model(prompt, caller="task_thinker.ask_model"):
    """Generyczne wołanie modelu dowolnym promptem (nie tylko analiza zadania).
    `caller` identyfikuje wywołanie w config/model_tiers.yaml — decyduje, jaki
    model użyć (np. Bożena/odbiór biznesowy woła z caller="bot_bozena_biznes.review",
    co daje wysoki poziom; web_answer/poprawka_materialu wołają z niskim).
    Nieznany caller -> tier "high" (fail-closed, patrz model_registry.py), więc
    domyślny caller="task_thinker.ask_model" (nieobecny w tabeli) też ląduje na
    wysokim poziomie — bezpieczny domyślny wybór, gdy wywołujący nic nie poda.

    Ta sama hierarchia co think(): Claude Code (claude login) -> SDK anthropic
    (ANTHROPIC_API_KEY) -> lokalny model tekstowy (Ollama). Nigdy nie rzuca.
    Zwraca {available, text, source, detail}."""
    claude_exe = _find_claude()
    if claude_exe:
        try:
            r = _think_via_claude_code(claude_exe, prompt, caller)
            if r.get("ok"):
                return {"available": True, "text": r["reasoning"], "source": "claude_code", "detail": "OK"}
        except (subprocess.TimeoutExpired, OSError):
            pass  # spróbujemy kolejnej ścieżki poniżej

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            r = _think_via_sdk(prompt, caller)
            if r and r.get("ok"):
                return {"available": True, "text": r["reasoning"], "source": "anthropic_sdk", "detail": "OK"}
        except Exception:  # noqa: BLE001 — fallback nie może wywalić wołającego
            pass

    text = _ask_ollama_text(prompt)
    if text is not None:
        return {"available": True, "text": text, "source": "ollama", "detail": "OK (lokalny model)"}

    return {"available": False, "text": None, "source": None,
            "detail": "Brak modelu (Claude Code / ANTHROPIC_API_KEY / Ollama) — nie mogę ocenić."}


def think(task, caller="task_thinker.think"):
    """Zwraca {available, ok, reasoning, detail, cost_usd, source}. Nigdy nie
    rzuca — błąd/timeout/brak modelu degraduje się do available/ok=False, żeby
    runner mógł dokończyć zadanie na samej klasyfikacji.

    `caller` -> poziom modelu przez config/model_tiers.yaml (domyślnie wysoki:
    analiza zadania to rozumowanie, nie mechaniczne wykonanie)."""
    prompt = build_prompt(task)
    claude_exe = _find_claude()
    if claude_exe:
        try:
            return _think_via_claude_code(claude_exe, prompt, caller, cwd=_safe_cwd(task))
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"available": True, "ok": False, "reasoning": None,
                    "detail": f"Claude Code niedostępny/timeout: {exc}", "cost_usd": 0.0, "source": "claude_code"}

    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            sdk_result = _think_via_sdk(prompt, caller)
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
