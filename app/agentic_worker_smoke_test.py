"""
Test dymny agentic_worker.py. Zero sieci i ZERO realnego wykonania —
bot_content_check.judge, task_thinker._find_claude i subprocess.run są
podmieniane atrapami. Atrapa subprocess.run sama zapisuje wynik.md w cwd
(symuluje efekt prawdziwego subagenta), żeby sprawdzić parsowanie/kontrakt
bez uruchamiania Claude Code.

Użycie:
    python agentic_worker_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import agentic_worker
import bot_content_check
import task_thinker

TASK = {"task_id": "T-AGENT", "title": "Podsumuj sprzedaż z ostatniego tygodnia",
        "expected_result": "Krótkie podsumowanie", "acceptance_criteria": "Konkretne liczby"}
THINKING_OK = {"ok": True, "reasoning": "Plan: przeanalizować dane i napisać podsumowanie.", "cost_usd": 0.0}


def _atrapa_judge(aligned, reasoning="ok", cost_usd=0.01):
    return lambda task, content, mode="wynik": {"aligned": aligned, "reasoning": reasoning,
                                                "cost_usd": cost_usd, "source": "claude_code"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_judge = bot_content_check.judge
    original_find_claude = task_thinker._find_claude
    original_run = agentic_worker.subprocess.run
    original_workspace = agentic_worker.WORKSPACE_DIR

    try:
        tmp = Path(tempfile.mkdtemp())
        agentic_worker.WORKSPACE_DIR = tmp

        # 1. Brak planu -> odmowa, subprocess.run NIE wywołane.
        agentic_worker.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(AssertionError("nie powinno się wywołać"))
        wynik_brak_planu = agentic_worker.run(TASK, {"ok": False, "reasoning": None})
        checks.append(("Brak planu -> executed=False", wynik_brak_planu["executed"] is False))

        # 2. Plan niedopasowany -> odmowa, subprocess.run NIE wywołane (zero zmarnowanego kosztu).
        bot_content_check.judge = _atrapa_judge(aligned=False, reasoning="Plan nie na temat.")
        wynik_zly_plan = agentic_worker.run(TASK, THINKING_OK)
        checks.append(("Plan niedopasowany -> executed=False", wynik_zly_plan["executed"] is False))
        checks.append(("Plan niedopasowany -> powód w acceptance_notes",
                       "Plan nie na temat" in wynik_zly_plan["acceptance_notes"]))

        # 3. Plan OK, ale brak Claude Code -> odmowa.
        bot_content_check.judge = _atrapa_judge(aligned=True)
        task_thinker._find_claude = lambda: None
        wynik_brak_claude = agentic_worker.run(TASK, THINKING_OK)
        checks.append(("Brak Claude Code -> executed=False", wynik_brak_claude["executed"] is False))
        task_thinker._find_claude = lambda: "claude"

        # 4. Plan OK, subprocess zwraca kod != 0 -> NIE WYKONANO.
        def _fake_run_error(cmd, **kwargs):
            class _Wynik:
                returncode = 1
                stdout = ""
                stderr = "błąd wykonania"
            return _Wynik()
        agentic_worker.subprocess.run = _fake_run_error
        wynik_blad = agentic_worker.run(TASK, THINKING_OK)
        # executed=False (NIE True) — zgodnie z kontraktem modułu (docstring: "błąd
        # wykonania ... -> executed=False ... runner_loop.py eskaluje wprost").
        # Realny bug 27.08.2026 (znaleziony w audycie): ten test wcześniej asercjował
        # executed=True, czyli UTRWALAŁ złe zachowanie zamiast je złapać — awaria
        # subagenta (zły kod wyjścia) mogła cicho zamknąć się jako "done" zamiast
        # trafić do człowieka.
        checks.append(("subprocess zwraca kod 1 -> executed=False (eskalacja w runner_loop), 'NIE WYKONANO'",
                       wynik_blad["executed"] is False and "NIE WYKONANO" in wynik_blad["acceptance_notes"]))

        # 4b. Błąd trafia na stdout, nie stderr (żywy bug 27.08.2026 — "You're out
        # of usage credits..." było niewidoczne, bo powód sprawdzał tylko stderr).
        def _fake_run_error_stdout(cmd, **kwargs):
            class _Wynik:
                returncode = 1
                stdout = "You're out of usage credits."
                stderr = ""
            return _Wynik()
        agentic_worker.subprocess.run = _fake_run_error_stdout
        wynik_blad_stdout = agentic_worker.run(TASK, THINKING_OK)
        checks.append(("Błąd na stdout (pusty stderr) trafia do acceptance_notes, nie ginie",
                       "usage credits" in wynik_blad_stdout["acceptance_notes"]))

        # 5. Sukces, ale subagent nie zostawił wynik.md -> NIE WYKONANO, executed=False.
        def _fake_run_no_file(cmd, **kwargs):
            class _Wynik:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Wynik()
        agentic_worker.subprocess.run = _fake_run_no_file
        wynik_brak_pliku = agentic_worker.run(TASK, THINKING_OK)
        checks.append(("Kod 0 ale brak wynik.md -> executed=False, 'NIE WYKONANO'",
                       wynik_brak_pliku["executed"] is False and "NIE WYKONANO" in wynik_brak_pliku["acceptance_notes"]))

        # 6. Happy path: subprocess "tworzy" wynik.md w cwd, komenda ma właściwe flagi.
        captured = {}

        def _fake_run_success(cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            (Path(kwargs["cwd"]) / "wynik.md").write_text(
                "Sprzedano 120 sztuk za 45 000 zł w tym tygodniu.", encoding="utf-8")

            class _Wynik:
                returncode = 0
                stdout = ""
                stderr = ""
            return _Wynik()
        agentic_worker.subprocess.run = _fake_run_success
        wynik_ok = agentic_worker.run(TASK, THINKING_OK)
        checks.append(("Happy path: executed=True", wynik_ok["executed"] is True))
        checks.append(("Happy path: acceptance_notes = treść wynik.md",
                       wynik_ok["acceptance_notes"] == "Sprzedano 120 sztuk za 45 000 zł w tym tygodniu."))
        checks.append(("Happy path: tool = agentic_task", wynik_ok["tool"] == "agentic_task"))
        checks.append(("Happy path: functional_checks wskazuje na wynik.md",
                       wynik_ok["functional_checks"][0]["target"].endswith("wynik.md")))
        checks.append(("Happy path: komenda ma --permission-mode acceptEdits",
                       "acceptEdits" in captured["cmd"]))
        checks.append(("Happy path: komenda ma --allowedTools z Read/Write/Edit/Skill/WebFetch/WebSearch",
                       "Read Write Edit Skill WebFetch WebSearch" in captured["cmd"]))
        checks.append(("Happy path: komenda ma --add-dir na folder zadania",
                       "--add-dir" in captured["cmd"] and captured["cwd"] in captured["cmd"]))
        checks.append(("Happy path: BRAK --dangerously-skip-permissions",
                       not any("dangerously-skip-permissions" in str(c) for c in captured["cmd"])))
        checks.append(("Happy path: cwd = folder zadania pod WORKSPACE_DIR",
                       str(tmp) in captured["cwd"] and "T-AGENT" in captured["cwd"]))
        checks.append(("Happy path: prompt zabrania usuwania plików",
                       "NIGDY nie usuwaj żadnego pliku" in captured["cmd"][4]))

        # 7. Kontekst firmy/projektu/rodzeństwa trafia do promptu (dokładany
        # PRZED "Zadanie: ..."), gdy dostępny.
        original_zbuduj = agentic_worker.kontekst_firmy.zbuduj
        agentic_worker.kontekst_firmy.zbuduj = lambda tekst: "--- KONTEKST FIRMY ---\nFikcyjna treść firmowa."

        class _FakeClient:
            def project_name(self, project_id):
                return "Projekt testowy"

        task_z_kontekstem = {**TASK, "project_id": "PRJ-1", "parent_task_id": "T-RODZIC",
                             "sibling_tasks": [{"title": "Inne podzadanie", "status": "todo"}]}
        agentic_worker.subprocess.run = _fake_run_success
        try:
            agentic_worker.run(task_z_kontekstem, THINKING_OK, _FakeClient())
            prompt_z_kontekstem = captured["cmd"][4]
        finally:
            agentic_worker.kontekst_firmy.zbuduj = original_zbuduj

        checks.append(("Kontekst firmy trafia do promptu PRZED treścią zadania",
                       "Fikcyjna treść firmowa" in prompt_z_kontekstem
                       and prompt_z_kontekstem.index("Fikcyjna treść firmowa") < prompt_z_kontekstem.index("Zadanie:")))
        checks.append(("Nazwa projektu (przez client.project_name) trafia do promptu",
                       "Projekt testowy" in prompt_z_kontekstem))
        checks.append(("Tytuł podzadania rodzeństwa trafia do promptu",
                       "Inne podzadanie" in prompt_z_kontekstem))

        # 8. Brak client / błąd project_name -> fail-soft, wykonanie się nie wywala.
        agentic_worker.kontekst_firmy.zbuduj = lambda tekst: (_ for _ in ()).throw(RuntimeError("błąd kontekstu"))
        try:
            wynik_bez_klienta = agentic_worker.run(TASK, THINKING_OK, None)
            checks.append(("Brak client / błąd kontekstu -> fail-soft, executed=True",
                           wynik_bez_klienta["executed"] is True))
        finally:
            agentic_worker.kontekst_firmy.zbuduj = original_zbuduj
    finally:
        bot_content_check.judge = original_judge
        task_thinker._find_claude = original_find_claude
        agentic_worker.subprocess.run = original_run
        agentic_worker.WORKSPACE_DIR = original_workspace

    print("\n--- Wynik testu dymnego agentic_worker ---")
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
