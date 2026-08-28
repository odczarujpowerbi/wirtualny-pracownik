"""
Test dymny integracyjny: pełny przebieg runner_loop.process_task() na zadaniu
BEZ rozpoznanego workera i BEZ podziału na podzadania (task_decomposer mówi
"nie dziel") — sprawdza, że użytkownik dostaje REALNY wynik subagenta
(agentic_worker.py), nie sam plan z task_thinker.think(). Mock: subprocess
(plan + bounded execution) i task_thinker.ask_model (task_decomposer +
bot_content_check) — zero sieci, zero prawdziwego Claude Code. Używa
TYMCZASOWEJ bazy i tymczasowych plików MockProjectlyClient.

Użycie:
    python agentic_worker_integration_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import agentic_worker
import email_client
import risk_classifier
import runner_loop
import state_store
import task_router
import task_thinker
from projectly_client import MockProjectlyClient

TASK = {"task_id": "T-REALNY-WYNIK", "title": "Podsumuj sprzedaż z ostatniego tygodnia",
        "expected_result": "Krótkie podsumowanie liczb sprzedaży", "acceptance_criteria": "Konkretne liczby",
        "description": "", "risk_level_hint": "yellow", "project_id": "PROJ-1"}

NIE_DZIEL_JSON = '{"split": false, "reasoning": "Da się zrobić wprost, jedno spójne zadanie.", "subtasks": []}'
PLAN_TEXT = "1. Sprawdzić dane sprzedaży. 2. Zsumować. 3. Napisać krótkie podsumowanie."
WYNIK_REALNY = "Sprzedano 120 sztuk za 45 000 zł w tym tygodniu — wzrost o 12% względem poprzedniego."


def _fake_ask_model_factory(wynik_aligned=True):
    def _fake(prompt, caller=None):
        if caller == "task_decomposer.decide":
            return {"available": True, "text": NIE_DZIEL_JSON, "source": "claude_code", "detail": "OK"}
        if caller == "bot_content_check.review":
            if "Oceń PLAN" in prompt:
                return {"available": True, "text": '{"aligned": true, "reasoning": "Plan adresuje zadanie."}',
                       "source": "claude_code", "detail": "OK"}
            aligned = "true" if wynik_aligned else "false"
            return {"available": True, "text": f'{{"aligned": {aligned}, "reasoning": "Ocena wyniku."}}',
                   "source": "claude_code", "detail": "OK"}
        if caller == "output_decider.decide":
            return {"available": True, "text": '{"format": "md", "reasoning": "Krótka notatka tekstowa."}',
                   "source": "claude_code", "detail": "OK"}
        return {"available": True, "text": "Poprawiona treść.", "source": "claude_code", "detail": "OK"}
    return _fake


class _FakeEmailClient:
    def send_email(self, to, subject, body_text, cc=None):
        return {"status": "ok (test)"}


def _fake_subprocess_run(cmd, **kwargs):
    # task_thinker.subprocess i agentic_worker.subprocess to TEN SAM obiekt
    # modułu (oba robią zwykłe "import subprocess") — jeden wspólny mock,
    # rozróżniający wywołania po obecności --permission-mode (unikalne dla
    # agentic_worker.run, plan z task_thinker.think() nigdy go nie ma).
    class _Wynik:
        returncode = 0
        stdout = ""
        stderr = ""

    if "--permission-mode" in cmd:
        (Path(kwargs["cwd"]) / "wynik.md").write_text(WYNIK_REALNY, encoding="utf-8")
        return _Wynik()
    wynik = _Wynik()
    wynik.stdout = PLAN_TEXT
    return wynik


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    tmp = Path(tempfile.mkdtemp())
    original_db_path = state_store.DB_PATH
    original_root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    original_ask_model = task_thinker.ask_model
    original_find_claude = task_thinker._find_claude
    original_thinker_run = task_thinker.subprocess.run
    original_workspace = agentic_worker.WORKSPACE_DIR
    original_get_email_client = email_client.get_email_client

    try:
        state_store.DB_PATH = tmp / "state.db"
        os.environ["ONEDRIVE_TASKS_ROOT"] = str(tmp / "Zadania-Agenta")
        task_thinker._find_claude = lambda: "claude"
        # Scenariusz 2 poniżej eskaluje (needs_approval) -> escalation.py wysyła
        # mail naprawdę. Bez tej atrapy ten test (wpięty w godzinowy self_check.py)
        # wysyłałby PRAWDZIWY mail przy każdym przebiegu (żywy incydent 25.08.2026).
        email_client.get_email_client = lambda: _FakeEmailClient()
        task_thinker.subprocess.run = _fake_subprocess_run
        agentic_worker.WORKSPACE_DIR = tmp / "agentic_tasks"

        # --- Scenariusz 1: happy path — content-check zatwierdza wynik ---
        task_thinker.ask_model = _fake_ask_model_factory(wynik_aligned=True)

        client = MockProjectlyClient()
        client._created_tasks_path = tmp / "created.json"
        client._comments_path = tmp / "comments.json"
        client._feedback_path = tmp / "feedback.json"
        client._agent_status_path = tmp / "agent_status.json"

        policy = risk_classifier.load_policy()
        routing = task_router.load_routing()
        result = runner_loop.process_task(dict(TASK), policy, routing, client)

        checks.append(("Happy path: status = done", result.get("status") == "done"))

        onedrive_root = Path(os.environ["ONEDRIVE_TASKS_ROOT"])
        folders = list(onedrive_root.glob("T-REALNY-WYNIK_*"))
        checks.append(("Happy path: dokładnie jeden folder wyniku", len(folders) == 1))
        if folders:
            wynik_files = list(folders[0].glob("wynik_*.*"))
            checks.append(("Happy path: dokładnie jeden plik wyniku w OneDrive", len(wynik_files) == 1))
            if wynik_files:
                # Kluczowy test: plik zawiera REALNY wynik subagenta, NIE plan.
                tresc = wynik_files[0].read_bytes()
                checks.append(("Happy path: plik wyniku zawiera REALNY wynik (liczby sprzedaży)",
                               b"120" in tresc or b"45" in tresc))
                checks.append(("Happy path: plik wyniku NIE zawiera tekstu planu",
                               b"Sprawdzi" not in tresc))

        agentic_folders = list((tmp / "agentic_tasks").glob("T-REALNY-WYNIK_*"))
        checks.append(("Happy path: folder roboczy subagenta powstał pod runs/agentic_tasks",
                       len(agentic_folders) == 1))

        # Komentarz na zadaniu ma klikalny link do folderu SharePoint z tym samym
        # zadaniem (decyzja właściciela 29.08.2026: chce od razu, wchodząc w
        # status zadania, mieć link do materiałów, bez ręcznego szukania folderu).
        komentarze_done = client._load(client._comments_path, default={})
        tresc_komentarzy = " ".join(komentarze_done.get("T-REALNY-WYNIK", []))
        checks.append(("Happy path: komentarz zawiera klikalny link do SharePoint",
                       "📁 Materiały:" in tresc_komentarzy and "https://" in tresc_komentarzy
                       and "T-REALNY-WYNIK" in tresc_komentarzy))

        # --- Scenariusz 2: content-check ODRZUCA wynik -> NIE może cicho skończyć się 'done' ---
        task_thinker.ask_model = _fake_ask_model_factory(wynik_aligned=False)
        client2 = MockProjectlyClient()
        client2._created_tasks_path = tmp / "created2.json"
        client2._comments_path = tmp / "comments2.json"
        client2._feedback_path = tmp / "feedback2.json"
        client2._agent_status_path = tmp / "agent_status2.json"
        task2 = dict(TASK, task_id="T-ODRZUCONY-WYNIK")
        result2 = runner_loop.process_task(task2, policy, routing, client2)
        comments2 = client2._load(client2._comments_path, default={})
        tekst_komentarzy = " ".join(comments2.get("T-ODRZUCONY-WYNIK", []))
        checks.append(("Odrzucony wynik: NIE kończy się cichym 'done' bez śladu problemu",
                       result2.get("status") in ("needs_approval", "done")
                       and ("zastrzeże" in tekst_komentarzy.lower() or "eskal" in tekst_komentarzy.lower()
                            or "brak" in tekst_komentarzy.lower() or "zabrak" in tekst_komentarzy.lower()
                            or result2.get("status") == "needs_approval")))

        # --- Scenariusz 3: subagent DOSTAJE zielone światło (plan zaakceptowany),
        # ale sam subprocess Claude Code pada (zły kod wyjścia) -> MUSI eskalować,
        # nie zamknąć się cicho jako 'done'. Realny bug 27.08.2026 (znaleziony w
        # audycie): agentic_worker._nie_wykonano() ustawiał executed=True dla
        # tego przypadku, więc runner_loop.py NIGDY nie wchodził w gałąź
        # `execution_result.get("executed") is False` — zadanie leciało dalej
        # normalną ścieżką (żółte -> bramka, albo zielone bez efektu -> auto-done)
        # z mylącym komentarzem "zielone bez efektu", tracąc informację, że
        # subagent w ogóle nie wykonał zadania.
        def _fake_subprocess_run_subagent_pada(cmd, **kwargs):
            class _Wynik:
                returncode = 0
                stdout = PLAN_TEXT
                stderr = ""
            if "--permission-mode" in cmd:
                wynik = _Wynik()
                wynik.returncode = 1
                wynik.stderr = "błąd wykonania (symulowany)"
                return wynik
            return _Wynik()
        task_thinker.ask_model = _fake_ask_model_factory(wynik_aligned=True)
        task_thinker.subprocess.run = _fake_subprocess_run_subagent_pada
        client3 = MockProjectlyClient()
        client3._created_tasks_path = tmp / "created3.json"
        client3._comments_path = tmp / "comments3.json"
        client3._feedback_path = tmp / "feedback3.json"
        client3._agent_status_path = tmp / "agent_status3.json"
        task3 = dict(TASK, task_id="T-SUBAGENT-PADA")
        result3 = runner_loop.process_task(task3, policy, routing, client3)
        checks.append(("Subagent pada (zły exit code) -> needs_approval, NIGDY cichy 'done'",
                       result3.get("status") == "needs_approval"))
    finally:
        task_thinker.ask_model = original_ask_model
        task_thinker._find_claude = original_find_claude
        task_thinker.subprocess.run = original_thinker_run
        agentic_worker.WORKSPACE_DIR = original_workspace
        email_client.get_email_client = original_get_email_client
        state_store.DB_PATH = original_db_path
        if original_root is None:
            os.environ.pop("ONEDRIVE_TASKS_ROOT", None)
        else:
            os.environ["ONEDRIVE_TASKS_ROOT"] = original_root

    print("\n--- Wynik testu integracyjnego agentic_worker (realny wynik, nie plan) ---")
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
