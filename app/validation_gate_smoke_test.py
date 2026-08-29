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

    # Wynik czysto tekstowy: każdy bot pomija (brak zrzutu, testów, powtórki).
    # To NIE jest wada jakości, bramka musi to odróżnić od odrzucenia, inaczej
    # zadanie idzie do człowieka z zastrzeżeniami "brak szczegółów".
    cfg_all = {
        "gate": {"enabled": True, "order": ["bartek", "franek", "oskar"], "required_approvals": 1, "mandatory": []},
        "bots": {"bartek": {"enabled": True}, "franek": {"enabled": True}, "oskar": {"enabled": True}},
    }
    gate_nic = bot_gustaw_bramka.run_gate(task, {"cost_usd": 0.0, "acceptance_notes": "Odpowiedź tekstowa."},
                                          config=cfg_all)
    checks.append(("Gustaw: wszystkie boty pominięte -> nothing_to_check, zero zastrzeżeń",
                   gate_nic["nothing_to_check"] is True and gate_nic["concerns"] == []
                   and gate_nic["passed"] is False))

    # Odrzucenie to co innego niż brak czego sprawdzać, nothing_to_check musi być False,
    # bo inaczej wynik z realną wadą zostałby wydany bez decyzji człowieka.
    checks.append(("Gustaw: odrzucenie (budżet) -> nothing_to_check False",
                   gate_cost["nothing_to_check"] is False))

    # Pominięcie Z ZASTRZEŻENIEM (zadanie wizualne bez zrzutu) to NIE jest
    # "brak czego sprawdzić": jest co powiedzieć człowiekowi.
    gate_uwaga = bot_gustaw_bramka.run_gate(task, {"cost_usd": 0.0, "tool": "capture_screenshot"}, config=cfg_all)
    checks.append(("Gustaw: same pominięcia, ale ze zastrzeżeniem -> nothing_to_check False",
                   gate_uwaga["concerns"] != [] and gate_uwaga["nothing_to_check"] is False))

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
