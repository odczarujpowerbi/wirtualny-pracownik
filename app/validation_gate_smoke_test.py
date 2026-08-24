"""
Test dymny bramki jakości (4 boty + Gustaw). Uruchamialny lokalnie bez kluczy
API — ścieżki botów zależne od modelu (Oskar) mają deterministyczne atrapy,
żeby test sprawdzał LOGIKĘ bramki, nie samą rozmowę z modelem.

Użycie:
    python validation_gate_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import bot_bartek_dubler
import bot_franek_funkcjonalny
import bot_gustaw_bramka
import bot_oskar_wizja
import task_thinker


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    task = {"title": "Raport INDEKA", "action_type": "report_build", "acceptance_criteria": "Kolumny zgodne"}

    # --- Bartek (regresja) ---
    same = bot_bartek_dubler.review(task, {"output": {"x": 1}, "rerun": lambda: {"x": 1}})
    checks.append(("Bartek: identyczna powtórka -> approved", same["verdict"] == "approved"))

    diff = bot_bartek_dubler.review(task, {"output": {"x": 1}, "rerun": lambda: {"x": 2}})
    checks.append(("Bartek: rozbieżna powtórka -> rejected", diff["verdict"] == "rejected"))

    def _boom():
        raise RuntimeError("nie powtarzalne")
    err = bot_bartek_dubler.review(task, {"output": {"x": 1}, "rerun": _boom})
    checks.append(("Bartek: błąd powtórki -> rejected", err["verdict"] == "rejected"))

    skip = bot_bartek_dubler.review(task, {"output": {"x": 1}})
    checks.append(("Bartek: brak rerun -> skipped", skip["verdict"] == "skipped"))

    # --- Franek (testy funkcjonalne) ---
    with tempfile.TemporaryDirectory() as tmp:
        good_file = Path(tmp) / "efekt.json"
        good_file.write_text('{"ok": true}', encoding="utf-8")
        ok = bot_franek_funkcjonalny.review(task, {"functional_checks": [
            {"name": "plik", "type": "file_exists", "target": str(good_file)},
            {"name": "json", "type": "json_valid", "target": str(good_file)},
            {"name": "liczba", "type": "numbers_match", "actual": 10.0, "expected": 10.2, "tolerance": 0.5},
        ]})
        checks.append(("Franek: wszystkie testy przechodzą -> approved", ok["verdict"] == "approved"))

        bad = bot_franek_funkcjonalny.review(task, {"functional_checks": [
            {"name": "brak", "type": "file_exists", "target": str(Path(tmp) / "nie_ma.txt")},
        ]})
        checks.append(("Franek: brakujący plik -> rejected", bad["verdict"] == "rejected"))

    unknown = bot_franek_funkcjonalny.review(task, {"functional_checks": [{"type": "cos_nieznanego"}]})
    checks.append(("Franek: nieznany typ testu -> rejected (fail-closed)", unknown["verdict"] == "rejected"))

    none = bot_franek_funkcjonalny.review(task, {})
    checks.append(("Franek: brak testów -> skipped", none["verdict"] == "skipped"))

    # --- Oskar (wizja) — bez zrzutu i bez modelu, ścieżki skip ---
    no_shot = bot_oskar_wizja.review(task, {})
    checks.append(("Oskar: brak zrzutu -> skipped", no_shot["verdict"] == "skipped"))

    # --- Gustaw (bramka) — Franek jako bot obowiązkowy (weto), bez modelu ---
    cfg = {
        "gate": {"enabled": True, "order": ["franek", "oskar"], "required_approvals": 1, "mandatory": ["franek"]},
        "bots": {"franek": {"enabled": True}, "oskar": {"enabled": True}},
    }
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "ok.json"
        f.write_text("{}", encoding="utf-8")
        exec_ok = {"cost_usd": 0.1, "acceptance_notes": "gotowe",
                   "functional_checks": [{"type": "file_exists", "target": str(f)}]}
        gate_ok = bot_gustaw_bramka.run_gate(task, exec_ok, config=cfg)
    checks.append(("Gustaw: Franek (obowiązkowy) zatwierdza -> passed", gate_ok["passed"] is True))

    # Franek obowiązkowy nie zatwierdza (brakujący plik) -> bramka nie przechodzi
    gate_fail = bot_gustaw_bramka.run_gate(
        task, {"cost_usd": 0.1, "acceptance_notes": "x",
              "functional_checks": [{"type": "file_exists", "target": str(Path(tmp) / "nie_ma.txt")}]},
        config=cfg)
    checks.append(("Gustaw: Franek odrzuca (obowiązkowy) -> nie passed", gate_fail["passed"] is False))

    # Kontrola zakresu kosztu (scope guard) blokuje przed botami
    task_over = dict(task, max_ai_cost_usd=1.0)
    gate_cost = bot_gustaw_bramka.run_gate(task_over, {"cost_usd": 5.0}, config=cfg)
    checks.append(("Gustaw: przekroczony budżet -> nie passed",
                   gate_cost["passed"] is False and any("budżet" in c.lower() for c in gate_cost["concerns"])))

    # --- Regresja: bot wpisany w config/validation_gate.yaml musi mieć wpis w
    # REGISTRY (inaczej wpis w YAML jest po cichu ignorowany, patrz docstring
    # bot_gustaw_bramka.py) ---
    checks.append(("REGISTRY zawiera 'content'", "content" in bot_gustaw_bramka.REGISTRY))
    config_realny = bot_gustaw_bramka.load_gate_config()
    order_realny = config_realny.get("gate", {}).get("order", [])
    checks.append(("config/validation_gate.yaml: 'content' w order",
                   "content" in order_realny))
    checks.append(("Każdy bot z order ma wpis w REGISTRY (zero cichych pominięć)",
                   all(name in bot_gustaw_bramka.REGISTRY for name in order_realny)))

    # Funkcjonalnie: order z realnego configu faktycznie WOŁA bota 'content'.
    original_ask_model = task_thinker.ask_model
    try:
        task_thinker.ask_model = lambda prompt, caller=None: {
            "available": True, "text": '{"aligned": true, "reasoning": "Pasuje do zadania."}',
            "source": "claude_code", "detail": "OK"}
        gate_content = bot_gustaw_bramka.run_gate(
            task, {"cost_usd": 0.1, "tool": "agentic_task", "acceptance_notes": "wynik"},
            config=config_realny)
    finally:
        task_thinker.ask_model = original_ask_model
    checks.append(("run_gate() z realnym configiem faktycznie wywołuje bota 'content'",
                   any(v["bot"] == "content" for v in gate_content["verdicts"])))

    print("\n--- Wynik testu dymnego bramki jakości ---")
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
