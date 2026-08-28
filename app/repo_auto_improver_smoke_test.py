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
import os
import shutil
import sys
import tempfile
from pathlib import Path

import cost_tracker
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


class _FakeProjectlyClient:
    """Atrapa dla _zaloguj_wynik/run_repo_improvement_cycle — bez niej test
    sięgnąłby po prawdziwego projectly_client.get_client() (ta maszyna ma
    realne poświadczenia) i wysłał realny komentarz do Projectly."""
    def __init__(self):
        self.komentarze = []

    def post_comment(self, task_id, text):
        self.komentarze.append((task_id, text))
        return True


def _zapisz_zdarzenia_needs_approval(task_id, now):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status="needs_approval", now=now)
    state_store.record_event(task_id, "block_closed", "needs_approval", now)


def _zapisz_zdarzenia_gate_failed(task_id, now, status="in_progress"):
    # status NIE "done" — status="done" jest ZAWSZE odrzucany (patrz test
    # "sygnal_problemu: status='done' odrzucony ZAWSZE..." niżej), niezależnie
    # od tego, co było w historii. "in_progress" jako placeholder na
    # "cokolwiek innego niż done/needs_approval" — realnie taki stan po
    # gate_failed dziś nie występuje (runner_loop kończy albo w "done", albo
    # w "needs_approval"), ale test i tak musi pilnować, że sama PĘTLA
    # wykrywania nie jest zepsuta, gdyby to się zmieniło.
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status=status, now=now)
    state_store.record_event(task_id, "quality_gate", "Bramka: NIE przeszło.", now, decision="gate_failed")
    state_store.record_event(task_id, "block_closed", status, now)


def _zapisz_zdarzenia_duplicate(task_id, now, status="in_progress"):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status=status, now=now)
    state_store.record_event(task_id, "duplicate_skip", status, now)
    state_store.record_event(task_id, "block_closed", status, now)


def _zapisz_zdarzenia_czyste(task_id, now):
    state_store.upsert_task(task_id, payload={**TASK, "task_id": task_id}, status="done", now=now)
    state_store.record_event(task_id, "quality_gate", "Bramka: PRZESZŁO.", now, decision="gate_passed")
    state_store.record_event(task_id, "block_closed", "done", now)


def _fake_run_factory(git_status_stdout="", gh_dostepne=True):
    """Buduje atrapę _run: 'worktree add' faktycznie tworzy pusty katalog (żeby
    dało się do niego coś zapisać jak prawdziwy subagent), 'worktree remove'
    faktycznie go kasuje (żeby dało się sprawdzić sprzątanie), 'git status'
    zwraca zadaną treść, 'gh' symuluje dostępność/brak CLI."""
    def _run(cmd, cwd=None, timeout=60, check=False, env=None):
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

    def _z_podsumowaniem(worktree, prompt, task_id=None):
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

        # status="done" jest ZAWSZE odrzucany (decyzja właściciela 25.08.2026),
        # nawet jeśli w historii był falstart (bramka odrzuciła, potem przeszła
        # po poprawce) — zadanie już jest wykonane, nic do przeglądania.
        _zapisz_zdarzenia_gate_failed("T-GATE-ALE-DONE", now, status="done")
        checks.append(("sygnal_problemu: status='done' odrzucony ZAWSZE, mimo bramka_odrzucila w historii",
                       rai.sygnal_problemu("T-GATE-ALE-DONE")[0] is None))
        _zapisz_zdarzenia_duplicate("T-DUP-ALE-DONE", now, status="done")
        checks.append(("sygnal_problemu: status='done' odrzucony ZAWSZE, mimo duplicate_skip w historii",
                       rai.sygnal_problemu("T-DUP-ALE-DONE")[0] is None))

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
        rai._uruchom_subagenta = lambda worktree, prompt, task_id=None: {"executed": True}
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

        def _run_ze_sledzeniem(cmd, cwd=None, timeout=60, check=False, env=None):
            if cmd[:1] == ["git"] and "worktree" in cmd and "add" in cmd:
                utworzone_katalogi.append(Path(cmd[-2]))
            return oryginalny_run(cmd, cwd=cwd, timeout=timeout, check=check, env=env)

        rai._run = _run_ze_sledzeniem
        rai.napraw_zadanie("T-GATE", "bramka_odrzucila", "historia")
        checks.append(("napraw_zadanie: worktree faktycznie posprzątany po zakończeniu",
                       len(utworzone_katalogi) == 1 and not utworzone_katalogi[0].exists()))

        # --- 7. run_repo_improvement_cycle: rate-limit nie gubi zadania między przebiegami ---
        # state_path PRZEKAZANY JAWNIE (jak w kacper_monitor_smoke_test.py) — domyślny
        # parametr funkcji wiąże się z STATE_PATH raz, przy definicji modułu, więc samo
        # podmienienie `rai.STATE_PATH` (jak dla state_store.DB_PATH) by go nie podmieniło.
        # client PRZEKAZANY JAWNIE (atrapa) — bez tego run_repo_improvement_cycle sam
        # sięgnąłby po projectly_client.get_client() i próbował wysłać PRAWDZIWY
        # komentarz do Projectly (ta maszyna ma realne poświadczenia w sekretach).
        fake_client_logow = _FakeProjectlyClient()
        cyklowy_state_path = tmp / "cykl_state.json"
        cursor_przed = state_store.max_event_id()
        cyklowy_state_path.write_text(
            json.dumps({"last_event_id": cursor_przed, "reviewed": {}, "kolejka": []}), encoding="utf-8")
        _zapisz_zdarzenia_gate_failed("T-CYKL-1", now)
        _zapisz_zdarzenia_gate_failed("T-CYKL-2", now)

        wynik_cyklu_1 = rai.run_repo_improvement_cycle(state_path=cyklowy_state_path, limit=1, client=fake_client_logow)
        checks.append(("cykl 1: naprawia dokładnie `limit` zadań", len(wynik_cyklu_1["naprawiono"]) == 1))
        checks.append(("cykl 1: drugie zadanie zostaje w kolejce (nie ginie)", wynik_cyklu_1["w_kolejce"] == 1))
        checks.append(("cykl 1: komentarz-log zapisany na zadaniu źródłowym (atrapa klienta)",
                       len(fake_client_logow.komentarze) == 1 and fake_client_logow.komentarze[0][0] == "T-CYKL-1"))

        wynik_cyklu_2 = rai.run_repo_improvement_cycle(state_path=cyklowy_state_path, limit=1, client=fake_client_logow)
        checks.append(("cykl 2: dobija zadanie zostawione w kolejce z cyklu 1",
                       len(wynik_cyklu_2["naprawiono"]) == 1 and wynik_cyklu_2["w_kolejce"] == 0))
        checks.append(("cykl 2: kolejny komentarz-log dopisany (łącznie 2)", len(fake_client_logow.komentarze) == 2))

        wynik_cyklu_3 = rai.run_repo_improvement_cycle(state_path=cyklowy_state_path, limit=1, client=fake_client_logow)
        checks.append(("cykl 3: te same zadania nie są naprawiane drugi raz",
                       len(wynik_cyklu_3["naprawiono"]) == 0))

        # --- 7b. run_repo_improvement_cycle: "brak_akcji" (awaria NARZĘDZIA) jest
        # ponawiane, NIE blokowane trwale jak "brak_zmian" — żywy bug 25-26.08.2026
        # (znaleziony w audycie 27.08.2026): 142 zadania padłe przez brak usunięcia
        # ANTHROPIC_API_KEY nigdy nie zostałyby ponowione mimo naprawy tego buga,
        # bo "brak_akcji" trafiało do `reviewed` na równi z "brak_zmian".
        retry_state_path = tmp / "retry_state.json"
        cursor_retry = state_store.max_event_id()
        retry_state_path.write_text(
            json.dumps({"last_event_id": cursor_retry, "reviewed": {}, "kolejka": []}), encoding="utf-8")
        _zapisz_zdarzenia_needs_approval("T-BRAK-AKCJI", now)

        rai._uruchom_subagenta = lambda worktree, prompt, task_id=None: {
            "executed": False, "powod": "symulowana awaria narzędzia (np. subagent chwilowo niedostępny)"}
        fake_client_retry = _FakeProjectlyClient()
        for i in range(rai.MAX_PROB_BRAK_AKCJI):
            wynik_retry = rai.run_repo_improvement_cycle(state_path=retry_state_path, limit=1, client=fake_client_retry)
            checks.append((f"retry brak_akcji: próba {i + 1}/{rai.MAX_PROB_BRAK_AKCJI} faktycznie podjęta",
                           len(wynik_retry["naprawiono"]) == 1
                           and wynik_retry["naprawiono"][0]["akcja"] == "brak_akcji"))
        stan_po_probach = json.loads(retry_state_path.read_text(encoding="utf-8"))
        checks.append((f"retry brak_akcji: po {rai.MAX_PROB_BRAK_AKCJI} próbach -> trwale w reviewed, nie w kolejce",
                       "T-BRAK-AKCJI" in stan_po_probach["reviewed"]
                       and "T-BRAK-AKCJI" not in stan_po_probach.get("kolejka", [])))

        wynik_po_limicie = rai.run_repo_improvement_cycle(state_path=retry_state_path, limit=1, client=fake_client_retry)
        checks.append(("retry brak_akcji: po wyczerpaniu prób KOLEJNY cykl już NIC nie robi (nie ponawia w nieskończoność)",
                       len(wynik_po_limicie["naprawiono"]) == 0))

        # --- 8. _uruchom_subagenta: woła Claude Code z --model (Fable 5) i Skill ---
        captured_cmd = {}
        captured_env = {}

        def _run_przechwytujacy(cmd, cwd=None, timeout=60, check=False, env=None):
            captured_cmd["cmd"] = cmd
            captured_env["env"] = env
            return _Wynik(0)
        rai._run = _run_przechwytujacy
        rai._uruchom_subagenta = original_uruchom  # implementacja realna, nie atrapa z kroku 5
        rai.os.environ["ANTHROPIC_API_KEY"] = "sk-test-nie-prawdziwy"
        try:
            rai._uruchom_subagenta(tmp, "prompt testowy")
        finally:
            del rai.os.environ["ANTHROPIC_API_KEY"]
        checks.append(("_uruchom_subagenta: komenda ma --model claude-opus-5 (tier 'high', cofnięte "
                       "z Fable 5 29.08.2026 - $200 spalone bez widoczności kosztu w Projectly)",
                       "--model" in captured_cmd["cmd"] and "claude-opus-5" in captured_cmd["cmd"]))
        checks.append(("_uruchom_subagenta: prompt zaraz po --model, PRZED --allowedTools",
                       captured_cmd["cmd"].index("prompt testowy") < captured_cmd["cmd"].index("--allowedTools")))
        checks.append(("_uruchom_subagenta: --allowedTools zawiera Skill",
                       "Read Write Edit Skill" in captured_cmd["cmd"]))
        checks.append(("_uruchom_subagenta: ANTHROPIC_API_KEY usunięty ze środowiska subprocesu "
                       "(żywy bug 25-26.08.2026: bez tego KAŻDE uruchomienie kończyło się błędem "
                       "'claude.ai connectors are disabled')",
                       captured_env["env"] is not None and "ANTHROPIC_API_KEY" not in captured_env["env"]))

        # --- 9. _plik_wyniku_tekst: czyta realny plik .md z OneDrive, fail-soft gdy brak ---
        original_onedrive_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
        try:
            onedrive_tmp = tmp / "onedrive"
            folder_zadania = onedrive_tmp / "T-ONEDRIVE_2026-08-25_test"
            folder_zadania.mkdir(parents=True)
            (folder_zadania / "wynik_T-ONEDRIVE.md").write_text(
                "Treść realnego wyniku zadania.", encoding="utf-8")
            (folder_zadania / "wynik_T-ONEDRIVE.pdf").write_bytes(b"%PDF-fake")
            os.environ["ONEDRIVE_TASKS_ROOT"] = str(onedrive_tmp)

            tresc = rai._plik_wyniku_tekst({"task_id": "T-ONEDRIVE"})
            checks.append(("_plik_wyniku_tekst: treść .md dołączona wprost", "Treść realnego wyniku" in tresc))
            checks.append(("_plik_wyniku_tekst: plik binarny tylko odnotowany z nazwy",
                           "wynik_T-ONEDRIVE.pdf" in tresc and "%PDF-fake" not in tresc))

            # Podzadanie (parent_task_id ustawione) -> szuka folderu RODZICA, nie
            # swojego id (żywy bug 26.08.2026, znaleziony w audycie 27.08.2026:
            # runner_loop._save_result_to_onedrive zapisuje wynik podzadania do
            # folderu rodzica, wcześniejsza wersja szukała po własnym task_id i
            # zawsze cicho dostawała "").
            tresc_podzadania = rai._plik_wyniku_tekst({"task_id": "T-SUBTASK", "parent_task_id": "T-ONEDRIVE"})
            checks.append(("_plik_wyniku_tekst: podzadanie znajduje wynik w folderze RODZICA",
                           "Treść realnego wyniku" in tresc_podzadania))

            del os.environ["ONEDRIVE_TASKS_ROOT"]
            checks.append(("_plik_wyniku_tekst: brak ONEDRIVE_TASKS_ROOT -> fail-soft ''",
                           rai._plik_wyniku_tekst({"task_id": "T-ONEDRIVE"}) == ""))
        finally:
            if original_onedrive_root is None:
                os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
            else:
                os.environ["ONEDRIVE_TASKS_ROOT"] = original_onedrive_root

        # --- 10. _zbuduj_prompt: zabrania usuwania plików ---
        prompt_testowy = rai._zbuduj_prompt(TASK, "bramka_odrzucila", "historia")
        checks.append(("_zbuduj_prompt: zabrania usuwania plików",
                       "NIGDY nie usuwaj żadnego pliku" in prompt_testowy))

        # --- 11. Koszt FAKTYCZNIE zgłaszany do cost_tracker (żywy bug 25-27.08.2026:
        # ten moduł nigdy nie zgłaszał kosztu - $200 spalone na Fable 5 bez śladu). ---
        rai._run = _run_przechwytujacy  # zwraca sukces (kod 0), nie tworzy zmian
        koszt_przed = cost_tracker.today_total()
        rai._uruchom_subagenta("T-KOSZT-WORKTREE", "prompt", "T-KOSZT")
        koszt_po = cost_tracker.today_total()
        checks.append(("_uruchom_subagenta: realne wywołanie subprocesu zgłasza koszt do cost_tracker",
                       koszt_po > koszt_przed))

        # Brak Claude Code w ogóle -> subprocess NIGDY nie wystartował -> BRAK kosztu.
        task_thinker._find_claude = lambda: None
        koszt_przed2 = cost_tracker.today_total()
        rai._uruchom_subagenta("T-WORKTREE", "prompt", "T-BRAK-CLAUDE")
        koszt_po2 = cost_tracker.today_total()
        checks.append(("_uruchom_subagenta: brak Claude Code -> BRAK zgłoszonego kosztu (zero realnej próby)",
                       koszt_po2 == koszt_przed2))
        task_thinker._find_claude = lambda: "claude"

        # --- 12. Bezpiecznik budżetu dobowego: "exceeded" wstrzymuje FAZĘ NAPRAWY
        # (drogi subagent), detekcja i tak leci dalej, nic nie ginie. ---
        original_budget_state = rai.cost_tracker.budget_state
        rai.cost_tracker.budget_state = lambda: {"level": "exceeded", "total": 999.0, "limit": 20.0, "percent": 4995.0}
        state_path_budzet = tmp / "budzet_state.json"
        cursor_budzet = state_store.max_event_id()
        state_path_budzet.write_text(
            json.dumps({"last_event_id": cursor_budzet, "reviewed": {}, "kolejka": []}), encoding="utf-8")
        _zapisz_zdarzenia_gate_failed("T-BUDZET", now)
        try:
            wynik_budzet = rai.run_repo_improvement_cycle(state_path=state_path_budzet, limit=1,
                                                           client=_FakeProjectlyClient())
        finally:
            rai.cost_tracker.budget_state = original_budget_state
        checks.append(("Budżet 'exceeded' -> ZERO napraw w tym przebiegu (drogi subagent wstrzymany)",
                       len(wynik_budzet["naprawiono"]) == 0 and "wstrzymano_budzetem" in wynik_budzet))
        checks.append(("Budżet 'exceeded' -> zadanie NADAL trafia do kolejki (detekcja leci dalej, nic nie ginie)",
                       wynik_budzet["w_kolejce"] == 1))
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
