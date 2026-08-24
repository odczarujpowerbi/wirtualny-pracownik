"""
Test dymny task_thinker — wyboru modelu przez model_registry (caller -> tier
-> model) i domyślnych poziomów think()/ask_model(). Bez sieci: subprocess
`claude -p` i klient anthropic są wstrzykiwane atrapami.

Kluczowy przypadek: wcześniej (przed migracją na rejestr) `_think_via_sdk`
miał zaszyty na trwałe jeden model dla WSZYSTKICH wywołań — ten test pilnuje,
że dwa różne callery dostają dwa różne modele.

Użycie:
    python task_thinker_smoke_test.py
"""

import os
import subprocess
import sys
import tempfile
import types
from pathlib import Path

import model_registry
import task_thinker


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- ścieżka Claude Code (subprocess) dostaje --model z rejestru ---
    # CLAUDE_TERMINAL_VISIBLE=0: te testy wołają _think_via_claude_code BEZ
    # visible_folder, więc i tak poszłyby ścieżką headless — ale wyłączamy
    # jawnie, żeby test nigdy nie zależał od domyślnego stanu przełącznika
    # (który jest WŁĄCZONY na maszynach produkcyjnych, patrz .env.example).
    original_visible = os.environ.get("CLAUDE_TERMINAL_VISIBLE")
    os.environ["CLAUDE_TERMINAL_VISIBLE"] = "0"
    captured = {}
    original_run = task_thinker.subprocess.run

    def _fake_run(cmd, **kwargs):
        captured["cmd"] = cmd

        class _Wynik:
            returncode = 0
            stdout = "analiza"
            stderr = ""
        return _Wynik()

    task_thinker.subprocess.run = _fake_run
    try:
        task_thinker._think_via_claude_code("claude", "prompt", "web_answer.answer")
        checks.append(("CLI: wykonawca (low) dostaje --model claude-sonnet-4-6",
                       "--model" in captured["cmd"] and "claude-sonnet-4-6" in captured["cmd"]))

        task_thinker._think_via_claude_code("claude", "prompt", "bot_oskar_wizja.review")
        checks.append(("CLI: osąd (high) dostaje --model claude-opus-5",
                       "--model" in captured["cmd"] and "claude-opus-5" in captured["cmd"]))

        task_thinker._think_via_claude_code("claude", "prompt", "nieznany.caller")
        checks.append(("CLI: nieznany caller -> fail-closed na opus-5",
                       "claude-opus-5" in captured["cmd"]))
    finally:
        task_thinker.subprocess.run = original_run
        if original_visible is None:
            os.environ.pop("CLAUDE_TERMINAL_VISIBLE", None)
        else:
            os.environ["CLAUDE_TERMINAL_VISIBLE"] = original_visible

    # --- ścieżka SDK dostaje inny model per caller + poprawny koszt ---
    class _FakeContentBlock:
        def __init__(self, text):
            self.type = "text"
            self.text = text

    class _FakeMessage:
        def __init__(self):
            self.content = [_FakeContentBlock("odpowiedz")]

    class _FakeMessages:
        def __init__(self):
            self.ostatni_model = None

        def create(self, model, max_tokens, messages):
            self.ostatni_model = model
            return _FakeMessage()

    class _FakeClient:
        def __init__(self):
            self.messages = _FakeMessages()

    fake_anthropic = types.SimpleNamespace(Anthropic=lambda: fake_client)
    fake_client = _FakeClient()
    sys.modules["anthropic"] = fake_anthropic
    try:
        wynik_low = task_thinker._think_via_sdk("prompt", "web_answer.answer")
        checks.append(("SDK: wykonawca (low) woła model Sonnet 4.6",
                       fake_client.messages.ostatni_model == "claude-sonnet-4-6"))
        checks.append(("SDK: koszt liczony wg cennika roli low (tańszy niż opus)",
                       wynik_low["cost_usd"] < task_thinker._think_via_sdk("x" * 4000, "task_thinker.think")["cost_usd"]))

        wynik_high = task_thinker._think_via_sdk("prompt", "task_thinker.think")
        checks.append(("SDK: analiza zadania (high) woła model Opus 5",
                       fake_client.messages.ostatni_model == "claude-opus-5"))
        checks.append(("SDK: wynik niesie użyty model", wynik_high.get("model") == "claude-opus-5"))
    finally:
        del sys.modules["anthropic"]

    # --- domyślne callery think()/ask_model() ---
    checks.append(("think() bez podania callera domyślnie idzie na wysoki poziom",
                   model_registry.tier_for_caller("task_thinker.think") == "high"))
    checks.append(("ask_model() bez podania callera domyślnie idzie na wysoki poziom "
                   "(nieznany caller jest fail-closed)",
                   model_registry.tier_for_caller("task_thinker.ask_model") == "high"))

    # --- widoczny terminal (task_thinker.think) — ZERO realnych okien: Popen podmieniony atrapą ---
    class _FakePopen:
        should_timeout = False
        last_cmd = None
        last_kwargs = None
        killed = False

        def __init__(self, cmd, **kwargs):
            _FakePopen.last_cmd = cmd
            _FakePopen.last_kwargs = kwargs
            _FakePopen.killed = False
            if not _FakePopen.should_timeout:
                (Path(kwargs["cwd"]) / "answer.txt").write_text("odpowiedz z widocznego okna", encoding="utf-8")

        def wait(self, timeout=None):
            if _FakePopen.should_timeout:
                raise subprocess.TimeoutExpired(cmd="claude", timeout=timeout)
            return 0

        def kill(self):
            _FakePopen.killed = True

    original_popen = task_thinker.subprocess.Popen
    original_visible2 = os.environ.get("CLAUDE_TERMINAL_VISIBLE")
    task_thinker.subprocess.Popen = _FakePopen
    try:
        # 1. Happy path: domyślnie włączone (CLAUDE_TERMINAL_VISIBLE niepodane) -> Popen woła,
        #    NIE subprocess.run, tworzy prompt.txt, czyta answer.txt.
        os.environ.pop("CLAUDE_TERMINAL_VISIBLE", None)
        tmp = Path(tempfile.mkdtemp())
        wynik = task_thinker._think_via_claude_code("claude", "prompt z $znakami `specjalnymi`", "task_thinker.think",
                                                     visible_folder=tmp)
        checks.append(("Widoczny terminal: domyślnie włączony -> Popen z CREATE_NEW_CONSOLE",
                       _FakePopen.last_kwargs.get("creationflags") == subprocess.CREATE_NEW_CONSOLE))
        checks.append(("Widoczny terminal: prompt trafia do prompt.txt, NIE do stringa komendy",
                       (tmp / "prompt.txt").read_text(encoding="utf-8") == "prompt z $znakami `specjalnymi`"
                       and "$znakami" not in _FakePopen.last_cmd[-1]))
        checks.append(("Widoczny terminal: wynik = treść answer.txt", wynik["reasoning"] == "odpowiedz z widocznego okna"))
        checks.append(("Widoczny terminal: ok=True, source=claude_code", wynik["ok"] is True and wynik["source"] == "claude_code"))

        # 2. Timeout -> kill() wywołane, fail-soft spada na subprocess.run (headless).
        _FakePopen.should_timeout = True
        original_run2 = task_thinker.subprocess.run
        task_thinker.subprocess.run = lambda *a, **k: type("W", (), {"returncode": 0, "stdout": "headless", "stderr": ""})()
        try:
            wynik_timeout = task_thinker._think_via_claude_code("claude", "prompt", "task_thinker.think",
                                                                 visible_folder=Path(tempfile.mkdtemp()))
            checks.append(("Widoczny terminal: timeout -> proc.kill() wywołane", _FakePopen.killed is True))
            checks.append(("Widoczny terminal: timeout -> fail-soft spada na headless (subprocess.run)",
                           wynik_timeout["reasoning"] == "headless"))
        finally:
            task_thinker.subprocess.run = original_run2
            _FakePopen.should_timeout = False

        # 3. CLAUDE_TERMINAL_VISIBLE=0 -> Popen NIE wywołane, idzie prosto headless.
        os.environ["CLAUDE_TERMINAL_VISIBLE"] = "0"
        _FakePopen.last_cmd = None
        task_thinker.subprocess.run = lambda *a, **k: type("W", (), {"returncode": 0, "stdout": "headless2", "stderr": ""})()
        try:
            wynik_off = task_thinker._think_via_claude_code("claude", "prompt", "task_thinker.think",
                                                             visible_folder=Path(tempfile.mkdtemp()))
            checks.append(("CLAUDE_TERMINAL_VISIBLE=0: Popen nie wywołane", _FakePopen.last_cmd is None))
            checks.append(("CLAUDE_TERMINAL_VISIBLE=0: idzie headless", wynik_off["reasoning"] == "headless2"))
        finally:
            task_thinker.subprocess.run = original_run2

        # 4. Platforma inna niż Windows -> headless, nawet z CLAUDE_TERMINAL_VISIBLE=1.
        os.environ["CLAUDE_TERMINAL_VISIBLE"] = "1"
        _FakePopen.last_cmd = None
        original_platform = task_thinker.sys.platform
        task_thinker.sys.platform = "linux"
        task_thinker.subprocess.run = lambda *a, **k: type("W", (), {"returncode": 0, "stdout": "headless3", "stderr": ""})()
        try:
            wynik_linux = task_thinker._think_via_claude_code("claude", "prompt", "task_thinker.think",
                                                               visible_folder=Path(tempfile.mkdtemp()))
            checks.append(("Platforma nie-Windows: Popen nie wywołane", _FakePopen.last_cmd is None))
            checks.append(("Platforma nie-Windows: idzie headless", wynik_linux["reasoning"] == "headless3"))
        finally:
            task_thinker.sys.platform = original_platform
            task_thinker.subprocess.run = original_run2
    finally:
        task_thinker.subprocess.Popen = original_popen
        if original_visible2 is None:
            os.environ.pop("CLAUDE_TERMINAL_VISIBLE", None)
        else:
            os.environ["CLAUDE_TERMINAL_VISIBLE"] = original_visible2

    print("\n--- Wynik testu dymnego task_thinker ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
