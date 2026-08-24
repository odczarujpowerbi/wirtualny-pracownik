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
import re
import shutil
import subprocess
import sys
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

# Folder per zadanie z widocznym oknem terminala (think() only) — patrz
# _run_in_visible_terminal. Zawsze pod runs/, nigdy śledzone w gicie.
TERMINAL_TASKS_DIR = APP_DIR / "runs" / "task_windows"


def _terminal_visible_enabled():
    """CLAUDE_TERMINAL_VISIBLE — domyślnie WŁĄCZONE (decyzja właściciela
    24.08.2026: chce widzieć na żywo, jak bot myśli nad złożonym zadaniem,
    do budowania zaufania na tym etapie projektu). '0'/'false' wyłącza na
    konkretnej maszynie (np. bez zalogowanej sesji RDP, gdzie okno nie
    wyświetli się nikomu)."""
    return os.environ.get("CLAUDE_TERMINAL_VISIBLE", "1").strip().lower() not in ("0", "false", "nie", "")


def _slug(text, limit=60):
    """Kopia runner_loop._slug — nie importować z runner_loop (cykliczny
    import: runner_loop już importuje task_thinker)."""
    slug = re.sub(r"[^\w\-]+", "_", text or "", flags=re.UNICODE).strip("_")
    return (slug[:limit] or "zadanie")

# Lokalny model tekstowy (Ollama) jako ostatni fallback wołania modelu —
# używany przez ask_model(), gdy nie ma ani Claude Code, ani klucza API.
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


def _run_in_visible_terminal(claude_exe, prompt, model, folder, env):
    """Odpala `claude -p` w NOWEJ, WIDOCZNEJ konsoli PowerShell (folder =
    app/runs/task_windows/<task_id>_<slug>/), żeby właściciel mógł widzieć na
    żywo, jak bot myśli nad złożonym zadaniem. Konsola zamyka się sama po
    zakończeniu (bez -NoExit).

    Zwraca dict jak _think_via_claude_code, albo None (fail-soft — wołający
    ma wtedy spaść na dotychczasową ścieżkę headless, NIGDY nie blokujemy
    przetworzenia zadania przez awarię samego okna).

    Prompt NIGDY nie wchodzi do stringa komendy PowerShell (unika problemów
    z cytowaniem/wstrzyknięciem znaków specjalnych typu $/`/") — zapisywany do
    pliku, komenda go tylko CZYTA przez Get-Content. Encoding UTF-8 wymuszony
    na konsoli i plikach — ten sam problem klasy, co env_bootstrap.py już raz
    naprawiał dla stdout (domyślna strona kodowa Windows łamie polskie znaki)."""
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        # Tee-Object w Windows PowerShell 5.1 NIE MA parametru -Encoding (błąd
        # znaleziony i zweryfikowany ręcznie 24.08.2026: "ParameterBindingException" —
        # cały pipeline padał po cichu, fail-soft spadał na headless bez odpowiedzi
        # w oknie). Obejście: Tee-Object -Variable (przelotem do konsoli) + Out-File
        # -Encoding utf8 osobno do pliku.
        cmd = (
            "chcp 65001 > $null; $OutputEncoding = [Console]::OutputEncoding = "
            "[System.Text.Encoding]::UTF8; "
            f"Get-Content -Raw -Encoding utf8 'prompt.txt' | & '{claude_exe}' -p --model {model} "
            "| Tee-Object -Variable odp; $odp | Out-File -FilePath 'answer.txt' -Encoding utf8"
        )
        proc = subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", cmd],
            cwd=str(folder),
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            env=env,
        )
        try:
            proc.wait(timeout=THINK_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            proc.kill()
            return None
        answer_path = folder / "answer.txt"
        if not answer_path.exists():
            return None
        text = answer_path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return None
    cost = cost_estimator.estimate_call("claude_code")
    return {"available": True, "ok": True, "reasoning": text,
            "detail": "OK", "cost_usd": cost, "source": "claude_code", "model": model}


def _think_via_claude_code(claude_exe, prompt, caller, cwd=None, visible_folder=None):
    """Wywołuje Claude Code headless. `caller` identyfikuje wywołanie w tabeli
    config/model_tiers.yaml (np. "task_thinker.think", "web_answer.answer") —
    stąd bierzemy poziom (high/low) i konkretny model (model_registry.resolve).
    cwd = repo zadania (kontekst) albo temp. Koszt subskrypcji szacowany proxy
    (cost_estimator), żeby kill switch liczył wolumen wywołań.

    `visible_folder` (tylko think(), patrz decyzja właściciela 24.08.2026):
    gdy podany i CLAUDE_TERMINAL_VISIBLE nie jest wyłączone i platforma to
    Windows, próbujemy najpierw widocznej konsoli (_run_in_visible_terminal);
    porażka (None) -> spadamy na dotychczasową ścieżkę headless poniżej, bez
    żadnej zmiany zachowania. ask_model() nigdy nie przekazuje tego parametru.

    ANTHROPIC_API_KEY jest USUWANY ze środowiska podprocesu (znaleziony
    23.08.2026): `claude` CLI traktuje obecność klucza jako priorytet nad
    logowaniem `claude login` i wyłącza connectory ("connectors are disabled
    because ANTHROPIC_API_KEY... takes precedence"), przez co `claude -p`
    zwracał kod 1 na KAŻDYM wywołaniu żywego runnera (klucz jest w
    secrets/.env, więc trafiał do środowiska każdego procesu). Zgodnie z
    docstringiem modułu główny model MA działać przez logowanie w terminalu,
    nie przez klucz — ten klucz jest dla innych skryptów (validator_visual.py
    i inne), nie dla tego wywołania."""
    role, model = model_registry.resolve(caller)
    cost = cost_estimator.estimate_call("claude_code")
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}

    if visible_folder is not None and _terminal_visible_enabled() and sys.platform == "win32":
        widoczny = _run_in_visible_terminal(claude_exe, prompt, model, visible_folder, env)
        if widoczny is not None:
            return widoczny
        # fail-soft: spadamy na ścieżkę headless poniżej, bez zmian

    result = subprocess.run(
        [claude_exe, "-p", "--model", model, prompt],
        cwd=cwd or tempfile.gettempdir(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=THINK_TIMEOUT_SECONDS,
        env=env,
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
    model użyć (np. Oskar/ocena wizualna woła z caller="bot_oskar_wizja.review",
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
        folder = TERMINAL_TASKS_DIR / f"{task.get('task_id') or 'zadanie'}_{_slug(task.get('title', ''))}"
        try:
            return _think_via_claude_code(claude_exe, prompt, caller, cwd=_safe_cwd(task), visible_folder=folder)
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
