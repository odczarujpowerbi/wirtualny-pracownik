"""
Krok 8 bootstrapu (SKALOWANIE.md sekcja 4): test dymny przed przekazaniem
nowego komputera do pracy. Przepuszcza jedno testowe zadanie przez pełen
cykl, sprawdza heartbeat i reakcję kill switcha. Odpowiednik scenariuszy
T-01/T-07 z planu testów dokumentacji bazowej, jako checklist odbioru
maszyny.

Ten test jest też wpięty w self_check.py, czyli chodzi GODZINOWO, w tle,
na zawsze — nie tylko raz, przy odbiorze maszyny. Dlatego (od 24.08.2026,
żywy incydent: Kacper zgłosił fałszywy alarm "quality_gate zawodzi
powtarzalnie", a dzienny koszt AI rósł bez realnej pracy):
  - state_store i ONEDRIVE_TASKS_ROOT są IZOLOWANE (tymczasowe), jak w
    task_decomposer_integration_smoke_test.py — inaczej fixture z
    mock_data/sample_tasks.json (PRJ-0005 ma na sztywno max_ai_cost_usd=0.0,
    więc bramka kosztowa odrzuca je z zasady) zapisywałby CO GODZINĘ
    "quality_gate failure" do PRAWDZIWEJ bazy, którą czyta kacper_monitor.py.
  - task_thinker.ask_model/think są podłożone atrapą "model niedostępny" —
    inaczej ten test woła NAPRAWDĘ Claude Code (koszt, zużycie limitu
    Anthropic) co godzinę, bez żadnej nowej informacji ponad to, co
    sprawdził już raz przy odbiorze maszyny. Mechanizm i tak jest przez to
    przetestowany w pełni: runner ma zdegradować się bez wywalenia pętli,
    gdy modelu nie ma — to jest droga, którą realnie przechodzi też każda
    świeżo postawiona maszyna przed `claude login`.

Użycie:
    python bootstrap_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import kill_switch
import runner_loop
import state_store
import task_thinker
import watchdog
from projectly_client import MockProjectlyClient

_BRAK_MODELU_ASK = {
    "available": False, "text": None, "source": None,
    "detail": "bootstrap_smoke_test: model celowo wyłączony (test godzinowy, nie realna praca).",
}
_BRAK_MODELU_THINK = {
    "available": False, "ok": False, "reasoning": None,
    "detail": "bootstrap_smoke_test: model celowo wyłączony (test godzinowy, nie realna praca).",
    "cost_usd": 0.0, "source": None,
}


def run():
    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    original_ask_model = task_thinker.ask_model
    original_think = task_thinker.think

    try:
        state_store.DB_PATH = tmp / "state.db"
        os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")
        task_thinker.ask_model = lambda prompt, caller=None: _BRAK_MODELU_ASK
        task_thinker.think = lambda task, caller=None: _BRAK_MODELU_THINK

        # Test dymny sprawdza MECHANIZM na danych testowych (mock), więc wymuszamy
        # MockProjectlyClient — niezależnie od tego, czy maszyna ma już wpisany token
        # do realnego Projectly. Realny Projectly może mieć akurat 0 zadań todo dla
        # konta AI tej roli, co NIE znaczy, że runner jest zepsuty.
        mock_client = MockProjectlyClient()

        print("1/3 — pełny cykl zadań przez runner_loop.run_once() (dane testowe/mock)...")
        results = runner_loop.run_once(client=mock_client)
        checks.append(("Runner przetworzył zadania z mock_data", len(results) > 0))

        print("2/3 — świeżość heartbeat...")
        hb_check = watchdog.check()
        checks.append(("Heartbeat świeży", hb_check["status"] == "ok"))

        print("3/3 — reakcja kill switcha...")
        kill_switch.activate("Test dymny bootstrapu.")
        blocked_results = runner_loop.run_once(client=mock_client)
        kill_switch.deactivate()
        checks.append(("Kill switch blokuje wykonanie", blocked_results == []))
    finally:
        task_thinker.ask_model = original_ask_model
        task_thinker.think = original_think
        state_store.DB_PATH = original_db_path
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu dymnego ---")
    all_passed = True
    for name, passed in checks:
        symbol = "✅" if passed else "❌"
        print(f"{symbol} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł — nie przekazuj komputera do pracy bez wyjaśnienia dlaczego.")
        sys.exit(1)

    print("\nWszystkie testy przeszły. Komputer gotowy do rejestracji (bootstrap_register.py).")


if __name__ == "__main__":
    run()
