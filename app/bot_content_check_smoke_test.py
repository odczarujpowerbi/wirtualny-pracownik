"""
Test dymny bot_content_check.py. Zero sieci — task_thinker.ask_model jest
podmieniany atrapą, żeby sprawdzić parsowanie/walidację/fail-closed bez
prawdziwego wywołania modelu.

Użycie:
    python bot_content_check_smoke_test.py
"""

import sys

import bot_content_check
import task_thinker

TASK = {"title": "Podsumuj sprzedaż z ostatniego tygodnia",
        "expected_result": "Krótkie podsumowanie liczb sprzedaży",
        "acceptance_criteria": "Konkretne liczby, nie ogólniki"}


def _atrapa(text, available=True, source="claude_code"):
    return lambda prompt, caller=None: {"available": available, "text": text,
                                        "source": source, "detail": "OK"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_ask_model = task_thinker.ask_model

    try:
        # 1. Happy path: model mówi aligned=True.
        task_thinker.ask_model = _atrapa('{"aligned": true, "reasoning": "Adresuje sedno zadania."}')
        ocena = bot_content_check.judge(TASK, "Sprzedano 120 sztuk za 45 000 zł w tym tygodniu.")
        checks.append(("Happy path: aligned=True", ocena["aligned"] is True))
        checks.append(("Happy path: koszt policzony (claude_code proxy > 0)", ocena["cost_usd"] > 0))

        # 2. Model mówi aligned=False (treść nie odpowiada zadaniu).
        task_thinker.ask_model = _atrapa('{"aligned": false, "reasoning": "To przepis na ciasto, nie podsumowanie sprzedaży."}')
        ocena_zle = bot_content_check.judge(TASK, "Przepis na szarlotkę: jabłka, cukier, mąka...")
        checks.append(("Model odrzuca niedopasowaną treść: aligned=False", ocena_zle["aligned"] is False))

        # 3. Brak treści -> aligned=False bez wołania modelu.
        task_thinker.ask_model = lambda *a, **k: (_ for _ in ()).throw(AssertionError("model nie powinien być wołany"))
        ocena_pusta = bot_content_check.judge(TASK, "   ")
        checks.append(("Pusta treść -> aligned=False, model NIE wołany", ocena_pusta["aligned"] is False))

        # 4. JSON nieparsowalny -> aligned=False (fail-closed), koszt i tak policzony.
        task_thinker.ask_model = _atrapa("Przepraszam, nie rozumiem polecenia.")
        ocena_smiec = bot_content_check.judge(TASK, "jakaś treść")
        checks.append(("Nieparsowalna odpowiedź -> aligned=False", ocena_smiec["aligned"] is False))
        checks.append(("Nieparsowalna odpowiedź -> koszt i tak policzony", ocena_smiec["cost_usd"] > 0))

        # 5. Model niedostępny -> aligned=False, koszt 0.0.
        task_thinker.ask_model = _atrapa(None, available=False)
        ocena_brak = bot_content_check.judge(TASK, "jakaś treść")
        checks.append(("Model niedostępny -> aligned=False", ocena_brak["aligned"] is False))
        checks.append(("Model niedostępny -> koszt 0.0", ocena_brak["cost_usd"] == 0.0))

        # 6. review(): pomija zadania spoza relevant_tools.
        task_thinker.ask_model = lambda *a, **k: (_ for _ in ()).throw(AssertionError("model nie powinien być wołany"))
        werdykt_skip = bot_content_check.review(TASK, {"tool": "fetch_url", "acceptance_notes": "x"})
        checks.append(("review(): narzędzie spoza relevant_tools -> skipped",
                       werdykt_skip["verdict"] == "skipped"))

        # 7. review(): agentic_task, aligned=True -> approved.
        task_thinker.ask_model = _atrapa('{"aligned": true, "reasoning": "Pasuje."}')
        werdykt_ok = bot_content_check.review(TASK, {"tool": "agentic_task", "acceptance_notes": "Wynik zgodny z zadaniem."})
        checks.append(("review(): agentic_task + aligned=True -> approved", werdykt_ok["verdict"] == "approved"))
        checks.append(("review(): werdykt niesie bota 'content'", werdykt_ok["bot"] == "content"))

        # 8. review(): agentic_task, aligned=False -> rejected, z concerns.
        task_thinker.ask_model = _atrapa('{"aligned": false, "reasoning": "Nie na temat."}')
        werdykt_zle = bot_content_check.review(TASK, {"tool": "agentic_task", "acceptance_notes": "Coś zupełnie innego."})
        checks.append(("review(): agentic_task + aligned=False -> rejected", werdykt_zle["verdict"] == "rejected"))
        checks.append(("review(): rejected niesie concerns", len(werdykt_zle["concerns"]) > 0))

        # 9. relevant_tools respektuje config przekazany z validation_gate.yaml.
        task_thinker.ask_model = _atrapa('{"aligned": true, "reasoning": "OK."}')
        werdykt_custom = bot_content_check.review(
            TASK, {"tool": "inny_tool", "acceptance_notes": "x"}, config={"relevant_tools": ["inny_tool"]})
        checks.append(("review(): respektuje config.relevant_tools niestandardowy",
                       werdykt_custom["verdict"] == "approved"))
    finally:
        task_thinker.ask_model = original_ask_model

    print("\n--- Wynik testu dymnego bot_content_check ---")
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
