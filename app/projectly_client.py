"""
Klient Projectly (PLAN-WDROZENIA.md sekcja 2, SKRYPTY.md `projectly_poller.py`
i pokrewne). To jest STUB — prawdziwe endpointy/autoryzacja Projectly nie są
mi znane z tej sesji (nie mam dostępu do dokumentacji API Projectly ani do
Twojego konta). Tryb mock pozwala testować cały pipeline (task_router,
risk_classifier, state_store, validator_pool, eskalacja) bez czekania na
te dane.

Do podłączenia prawdziwego Projectly: zaimplementuj metody klasy
ProjectlyClient używając realnego REST API/MCP, korzystając z kluczy z
lokalnego magazynu sekretów (nigdy nie wklejaj ich tutaj).
"""

import json
import os
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem PROJECTLY_API_KEY

MOCK_TASKS_PATH = Path(__file__).parent / "mock_data" / "sample_tasks.json"
MOCK_RUNS_DIR = Path(__file__).parent / "runs"


class ProjectlyClient:
    """Prawdziwa implementacja — DO ZROBIENIA, gdy będą znane endpointy/auth Projectly."""

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key
        self.base_url = base_url

    def get_new_tasks(self):
        raise NotImplementedError(
            "Prawdziwe API Projectly nie jest jeszcze podłączone. "
            "Użyj MockProjectlyClient do testów albo uzupełnij tę metodę."
        )

    def post_comment(self, task_id, text):
        raise NotImplementedError("Jak wyżej.")

    def update_status(self, task_id, status):
        raise NotImplementedError("Jak wyżej.")

    def create_task(self, title, description, assigned_to, parent_task_id=None):
        """Tworzy nowe zadanie w Projectly — używane przez escalate_to_human.py
        i continuation_task_creator.py (PLAN-WDROZENIA.md sekcja 4)."""
        raise NotImplementedError("Jak wyżej.")

    def get_comments(self, task_id):
        """Zwraca komentarze na zadaniu — używane przez human_response_validator.py."""
        raise NotImplementedError("Jak wyżej.")

    def publish_status(self, role, payload):
        """Nadpisuje stały wpis 'status na żywo' dla danej roli
        (live_status_publisher.py, PLAN-WDROZENIA.md sekcja 2)."""
        raise NotImplementedError("Jak wyżej.")

    def list_tasks(self, project_id=None, status=None):
        """Lista zadań z polami zgodnymi z realnym, potwierdzonym schematem
        Projectly (sprawdzonym w tej sesji przez MCP: title, status
        todo/in_progress/done, dueDate, estimatedHours, assignee) — używane
        przez digest_generator.py. UWAGA: Projectly nie ma dziś (patrz
        PROJECTLY-ROZWOJ.md) pola daty realnego wykonania — digest poniżej
        dlatego bazuje na statusie i dueDate, nie na tym, KIEDY coś naprawdę
        się skończyło."""
        raise NotImplementedError("Jak wyżej.")


class MockProjectlyClient:
    """Symuluje Projectly przy użyciu lokalnych plików JSON — do testowania
    Fazy 0-3 bez prawdziwego dostępu do API (PRZED-PILOTAZEM.md: sandbox vs
    produkcja; tu: mock vs realne API). Nowo utworzone zadania i status na
    żywo trafiają do runs/mock_created_tasks.json i runs/mock_live_status.json,
    żeby dało się je zweryfikować po przebiegu."""

    def __init__(self, tasks_path=MOCK_TASKS_PATH, project_tasks_path=None):
        self.tasks_path = tasks_path
        self.project_tasks_path = project_tasks_path or Path(__file__).parent / "mock_data" / "sample_project_tasks.json"
        self._created_tasks_path = MOCK_RUNS_DIR / "mock_created_tasks.json"
        self._comments_path = MOCK_RUNS_DIR / "mock_comments.json"
        self._live_status_path = MOCK_RUNS_DIR / "mock_live_status.json"

    def get_new_tasks(self):
        with open(self.tasks_path, encoding="utf-8") as f:
            return json.load(f)

    def post_comment(self, task_id, text):
        print(f"[MOCK Projectly] komentarz na {task_id}:\n{text}\n")
        comments = self._load(self._comments_path, default={})
        comments.setdefault(task_id, []).append(text)
        self._save(self._comments_path, comments)
        return True

    def update_status(self, task_id, status):
        print(f"[MOCK Projectly] {task_id} -> status: {status}")
        return True

    def create_task(self, title, description, assigned_to, parent_task_id=None):
        tasks = self._load(self._created_tasks_path, default=[])
        new_id = f"PRJ-ESC-{len(tasks) + 1:04d}"
        record = {
            "task_id": new_id,
            "title": title,
            "description": description,
            "assigned_to": assigned_to,
            "parent_task_id": parent_task_id,
        }
        tasks.append(record)
        self._save(self._created_tasks_path, tasks)
        print(f"[MOCK Projectly] utworzono zadanie {new_id} dla {assigned_to}: {title}")
        return new_id

    def get_comments(self, task_id):
        comments = self._load(self._comments_path, default={})
        return comments.get(task_id, [])

    def publish_status(self, role, payload):
        statuses = self._load(self._live_status_path, default={})
        statuses[role] = payload
        self._save(self._live_status_path, statuses)
        print(f"[MOCK Projectly] status na żywo ({role}): {payload}")
        return True

    def list_tasks(self, project_id=None, status=None):
        tasks = self._load(self.project_tasks_path, default=[])
        if project_id:
            tasks = [t for t in tasks if t.get("project_id") == project_id]
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return tasks

    @staticmethod
    def _load(path, default):
        if not path.exists():
            return default
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _save(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def get_client():
    """Zwraca realnego klienta, jeśli PROJECTLY_API_KEY jest ustawiony w
    środowisku, inaczej mock — żeby runner_loop.py dało się uruchomić od razu,
    bez czekania na prawdziwe dane dostępowe."""
    api_key = os.environ.get("PROJECTLY_API_KEY")
    if api_key:
        return ProjectlyClient(api_key=api_key, base_url=os.environ.get("PROJECTLY_BASE_URL"))
    return MockProjectlyClient()
