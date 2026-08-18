"""
Test dymny bramki jakości (5 botów + Gustaw). Uruchamialny lokalnie bez kluczy
API — ocena modelu (Bożena) jest podmieniana na deterministyczną atrapę, żeby
test sprawdzał LOGIKĘ bramki, nie samą rozmowę z modelem.

Użycie:
    python validation_gate_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import bot_bartek_dubler
import bot_bozena_biznes
import bot_franek_funkcjonalny
import bot_gustaw_bramka
import bot_oskar_wizja
import task_thinker


def _fake_model(answer_text, available=True):
    def _ask(prompt):
        return {"available": available, "text": answer_text, "source": "atrapa", "detail": "test"}
    return _ask


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

    # --- Bożena (odbiór biznesowy) z atrapą modelu ---
    original_ask = task_thinker.ask_model
    try:
        task_thinker.ask_model = _fake_model("AKCEPTACJA: tak\nUZASADNIENIE: dobre\nZASTRZEŻENIA:\n- brak")
        acc = bot_bozena_biznes.review(task, {"acceptance_notes": "Zbudowano raport."})
        checks.append(("Bożena: model akceptuje -> approved", acc["verdict"] == "approved"))

        task_thinker.ask_model = _fake_model("AKCEPTACJA: nie\nUZASADNIENIE: złe liczby\nZASTRZEŻENIA:\n- liczby się nie zgadzają")
        rej = bot_bozena_biznes.review(task, {"acceptance_notes": "Coś tam."})
        checks.append(("Bożena: model odrzuca -> rejected z zastrzeżeniem",
                       rej["verdict"] == "rejected" and any("liczby" in c for c in rej["concerns"])))

        task_thinker.ask_model = _fake_model(None, available=False)
        nomodel = bot_bozena_biznes.review(task, {"acceptance_notes": "x"})
        checks.append(("Bożena: brak modelu -> skipped (fail-closed)", nomodel["verdict"] == "skipped"))

        # --- Gustaw (bramka) — z atrapą Bożeny akceptującej ---
        task_thinker.ask_model = _fake_model("AKCEPTACJA: tak\nUZASADNIENIE: ok\nZASTRZEŻENIA:\n- brak")
        cfg = {
            "gate": {"enabled": True, "order": ["franek", "bozena"], "required_approvals": 2, "mandatory": ["bozena"]},
            "bots": {"franek": {"enabled": True}, "bozena": {"enabled": True}},
        }
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "ok.json"
            f.write_text("{}", encoding="utf-8")
            exec_ok = {"cost_usd": 0.1, "acceptance_notes": "gotowe",
                       "functional_checks": [{"type": "file_exists", "target": str(f)}]}
            gate_ok = bot_gustaw_bramka.run_gate(task, exec_ok, config=cfg)
        checks.append(("Gustaw: Franek+Bożena OK -> passed", gate_ok["passed"] is True))

        # Bożena obowiązkowa nie akceptuje -> bramka nie przechodzi
        task_thinker.ask_model = _fake_model("AKCEPTACJA: nie\nUZASADNIENIE: nie\nZASTRZEŻENIA:\n- źle")
        gate_fail = bot_gustaw_bramka.run_gate(task, {"cost_usd": 0.1, "acceptance_notes": "x"}, config=cfg)
        checks.append(("Gustaw: Bożena odrzuca (obowiązkowa) -> nie passed", gate_fail["passed"] is False))

        # Kontrola zakresu kosztu (scope guard) blokuje przed botami
        task_over = dict(task, max_ai_cost_usd=1.0)
        task_thinker.ask_model = _fake_model("AKCEPTACJA: tak\nUZASADNIENIE: ok\nZASTRZEŻENIA:\n- brak")
        gate_cost = bot_gustaw_bramka.run_gate(task_over, {"cost_usd": 5.0}, config=cfg)
        checks.append(("Gustaw: przekroczony budżet -> nie passed",
                       gate_cost["passed"] is False and any("budżet" in c.lower() for c in gate_cost["concerns"])))
    finally:
        task_thinker.ask_model = original_ask

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
