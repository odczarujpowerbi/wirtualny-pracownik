"""
Test dymny repo_auto_improver.py. Zero sieci i zero realnego gita/Claude Code:
jedyny punkt wywołania subprocess (`repo_auto_improver._run`) i
`task_thinker._find_claude` są podmieniane atrapami. `state_store.DB_PATH` i
`repo_auto_improver.STATE_PATH` izolowane (tymczasowe), jak w
task_decomposer_integration_smoke_test.py — zero wpływu na realne dane.

Użycie:
    python repo_auto_improver_smoke_test.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

import repo_auto_improver as rai
import state_store
import task_thinker

TASK = {"title": "Analiza czegoś", "expected_result": "Raport",
        "acceptance_criteria": "Zgodny z zadaniem", "project_id": "PROJ-1"}


class _Wynik:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _zapisz_zdarzenia_needs_approval(task_id, now):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status="needs_approval", now=now)
    state_store.record_event(task_id, "block_closed", "needs_approval", now)


def _zapisz_zdarzenia_gate_failed(task_id, now):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status="done", now=now)
    state_store.record_event(task_id, "quality_gate", "Bramka: NIE przeszło.", now, decision="gate_failed")
    state_store.record_event(task_id, "block_closed", "done", now)


def _zapisz_zdarzenia_duplicate(task_id, now):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status="done", now=now)
    state_store.record_event(task_id, "duplicate_skip", "done", now)
    state_store.record_event(task_id, "block_closed", "done", now)


def _zapisz_zdarzenia_czyste(task_id, now):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status="done", now=now)
    state_store.record_event(task_id, "quality_gate", "Bramka: PRZESZŁO.", now, decision="gate_passed")
    state_store.record_event(task_id, "block_closed", "done", now)


def _fake_run_factory(git_status_stdout="", gh_dostepne=True):
    """Buduje atrapę _run: 'worktree add' faktycznie tworzy pusty katalog (żeby
    dało się do niego coś zapisać jak prawdziwy subagent), 'worktree remove'
    faktycznie go kasuje (żeby dało się sprawdzić sprzątanie), 'git status'
    zwraca zadaną treść, 'gh' symuluje dostępność/brak CLI."""
    def _run(cmd, cwd=None, timeout=60, check=False):
        if cmd[:1] == ["git"] and "worktree" in cmd and "add" in cmd:
            Path(cmd[-2]).mkdir(parents=True, exist_ok=True)
            return _Wynik(0)
        if cmd[:1] == ["git"] and "worktree" in cmd and "remove" in cmd:
            shutil.rmtree(cmd[-1], ignore_errors=True)
            return _Wynik(0)
        if cmd[:1] == ["git"] and "status" in cmd:
            return _Wynik(0, stdout=git_status_stdout)
        if cmd[:1] == ["gh"]:
            if not gh_dostepne:
                return _Wynik(1, stderr="gh: command not found")
            return _Wynik(0, stdout="https://github.com/example/repo/pull/1\n")
        return _Wynik(0)
    return _run


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_state_path = rai.STATE_PATH
    original_run = rai._run
    original_which = rai.shutil.which
    original_find_claude = task_thinker._find_claude
    original_uruchom = rai._uruchom_subagenta
    now = "2026-08-25T10:00:00+00:00"

    def _z_podsumowaniem(worktree, prompt):
        (worktree / rai.RESULT_FILENAME).write_text("Naprawiono routing MailerLite.", encoding="utf-8")
        return {"executed": True}

    try:
        state_store.DB_PATH = tmp / "state.db"
        rai.STATE_PATH = tmp / "repo_improver_state.json"
        task_thinker._find_claude = lambda: "claude"

        # --- 1. sygnal_problemu: cztery przypadki + nieznane task_id ---
        _zapisz_zdarzenia_needs_approval("T-ESK", now)
        checks.append(("sygnal_problemu: eskalacja -> 'eskalacja_do_czlowieka'",
                       rai.sygnal_problemu("T-ESK")[0] == "eskalacja_do_czlowieka"))

        _zapisz_zdarzenia_gate_failed("T-GATE", now)
        checks.append(("sygnal_problemu: bramka odrzuciła -> 'bramka_odrzucila'",
                       rai.sygnal_problemu("T-GATE")[0] == "bramka_odrzucila"))

        _zapisz_zdarzenia_duplicate("T-DUP", now)
        checks.append(("sygnal_problemu: podwójne wykonanie -> 'podwojne_wykonanie'",
                       rai.sygnal_problemu("T-DUP")[0] == "podwojne_wykonanie"))

        _zapisz_zdarzenia_czyste("T-OK", now)
        checks.append(("sygnal_problemu: czyste 'done' -> brak sygnału", rai.sygnal_problemu("T-OK")[0] is None))
        checks.append(("sygnal_problemu: nieznane task_id -> brak sygnału", rai.sygnal_problemu("BRAK")[0] is None))

        # --- 2. napraw_zadanie: pełna ścieżka szczęśliwa (zmiany + gh dostępne) ---
        rai.shutil.which = lambda name: "/usr/bin/gh"  # host testu może NIE mieć gh — nie polegamy na środowisku
        rai._run = _fake_run_factory(git_status_stdout=" M app/foo.py\n", gh_dostepne=True)
        rai._uruchom_subagenta = _z_podsumowaniem
        wynik = rai.napraw_zadanie("T-GATE", "bramka_odrzucila", "historia")
        checks.append(("napraw_zadanie: PR utworzony gdy są zmiany + gh dostępne",
                       wynik["akcja"] == "pr_utworzony" and wynik.get("url", "").startswith("https://")))
        checks.append(("napraw_zadanie: branch nazwany auto-fix/...", wynik["branch"].startswith("auto-fix/t-gate-")))

        # --- 3. napraw_zadanie: subagent nie znalazł nic do poprawy ---
        rai._run = _fake_run_factory(git_status_stdout="", gh_dostepne=True)
        rai._uruchom_subagenta = lambda worktree, prompt: {"executed": True}
        wynik_brak = rai.napraw_zadanie("T-GATE", "bramka_odrzucila", "historia")
        checks.append(("napraw_zadanie: brak zmian -> akcja='brak_zmian'", wynik_brak["akcja"] == "brak_zmian"))

        # --- 4. napraw_zadanie: brak Claude Code -> brak_akcji ---
        task_thinker._find_claude = lambda: None
        rai._uruchom_subagenta = original_uruchom  # realna implementacja, sprawdzi _find_claude
        wynik_brak_modelu = rai.napraw_zadanie("T-GATE", "bramka_odrzucila", "historia")
        checks.append(("napraw_zadanie: brak Claude Code -> akcja='brak_akcji'",
                       wynik_brak_modelu["akcja"] == "brak_akcji"))
        task_thinker._find_claude = lambda: "claude"

        # --- 5. napraw_zadanie: są zmiany, ale brak `gh` -> branch_bez_pr ---
        rai.shutil.which = lambda name: None
        rai._run = _fake_run_factory(git_status_stdout=" M app/foo.py\n", gh_dostepne=False)
        rai._uruchom_subagenta = _z_podsumowaniem
        wynik_bez_gh = rai.napraw_zadanie("T-GATE", "bramka_odrzucila", "historia")
        checks.append(("napraw_zadanie: brak `gh` -> akcja='branch_bez_pr'", wynik_bez_gh["akcja"] == "branch_bez_pr"))

        # --- 6. napraw_zadanie: worktree faktycznie sprzątnięty w każdym przypadku ---
        rai.shutil.which = lambda name: "/usr/bin/gh"
        rai._run = _fake_run_factory(git_status_stdout=" M app/foo.py\n", gh_dostepne=True)
        utworzone_katalogi = []
        oryginalny_run = rai._run

        def _run_ze_sledzeniem(cmd, cwd=None, timeout=60, check=False):
            if cmd[:1] == ["git"] and "worktree" in cmd and "add" in cmd:
                utworzone_katalogi.append(Path(cmd[-2]))
            return oryginalny_run(cmd, cwd=cwd, timeout=timeout, check=check)

        rai._run = _run_ze_sledzeniem
        rai.napraw_zadanie("T-GATE", "bramka_odrzucila", "historia")
        checks.append(("napraw_zadanie: worktree faktycznie posprzątany po zakończeniu",
                       len(utworzone_katalogi) == 1 and not utworzone_katalogi[0].exists()))

        # --- 7. run_repo_improvement_cycle: rate-limit nie gubi zadania między przebiegami ---
        # state_path PRZEKAZANY JAWNIE (jak w kacper_monitor_smoke_test.py) — domyślny
        # parametr funkcji wiąże się z STATE_PATH raz, przy definicji modułu, więc samo
        # podmienienie `rai.STATE_PATH` (jak dla state_store.DB_PATH) by go nie podmieniło.
        cyklowy_state_path = tmp / "cykl_state.json"
        cursor_przed = state_store.max_event_id()
        cyklowy_state_path.write_text(
            json.dumps({"last_event_id": cursor_przed, "reviewed": {}, "kolejka": []}), encoding="utf-8")
        _zapisz_zdarzenia_gate_failed("T-CYKL-1", now)
        _zapisz_zdarzenia_gate_failed("T-CYKL-2", now)

        wynik_cyklu_1 = rai.run_repo_improvement_cycle(state_path=cyklowy_state_path, limit=1)
        checks.append(("cykl 1: naprawia dokładnie `limit` zadań", len(wynik_cyklu_1["naprawiono"]) == 1))
        checks.append(("cykl 1: drugie zadanie zostaje w kolejce (nie ginie)", wynik_cyklu_1["w_kolejce"] == 1))

        wynik_cyklu_2 = rai.run_repo_improvement_cycle(state_path=cyklowy_state_path, limit=1)
        checks.append(("cykl 2: dobija zadanie zostawione w kolejce z cyklu 1",
                       len(wynik_cyklu_2["naprawiono"]) == 1 and wynik_cyklu_2["w_kolejce"] == 0))

        wynik_cyklu_3 = rai.run_repo_improvement_cycle(state_path=cyklowy_state_path, limit=1)
        checks.append(("cykl 3: te same zadania nie są naprawiane drugi raz",
                       len(wynik_cyklu_3["naprawiono"]) == 0))
    finally:
        rai._run = original_run
        rai.shutil.which = original_which
        rai._uruchom_subagenta = original_uruchom
        task_thinker._find_claude = original_find_claude
        state_store.DB_PATH = original_db_path
        rai.STATE_PATH = original_state_path

    print("\n--- Wynik testu dymnego repo_auto_improver ---")
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
