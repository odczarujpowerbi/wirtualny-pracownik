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

import sys
import types

import model_registry
import task_thinker


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- ścieżka Claude Code (subprocess) dostaje --model z rejestru ---
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

        task_thinker._think_via_claude_code("claude", "prompt", "bot_bozena_biznes.review")
        checks.append(("CLI: osąd (high) dostaje --model claude-opus-5",
                       "--model" in captured["cmd"] and "claude-opus-5" in captured["cmd"]))

        task_thinker._think_via_claude_code("claude", "prompt", "nieznany.caller")
        checks.append(("CLI: nieznany caller -> fail-closed na opus-5",
                       "claude-opus-5" in captured["cmd"]))
    finally:
        task_thinker.subprocess.run = original_run

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
