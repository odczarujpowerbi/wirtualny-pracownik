"""
Klient Projectly (PLAN-WDROZENIA.md sekcja 2). Dwie implementacje:

- ProjectlyClient — REALNY, przez MCP (mcp_client.py). Każda metoda mówi, które
  narzędzie MCP wywołuje i w jakiej sytuacji. Pełna mapa: config/projectly.yaml
  sekcja mcp_tool_usage.
- MockProjectlyClient — lokalne pliki JSON, do testów całego pipeline bez sieci.

get_client() zwraca realnego, gdy jest PROJECTLY_API_KEY, inaczej mock — więc
runner_loop.py działa od razu, bez kluczy.

Które narzędzie MCP do czego (zaszyta wiedza, spójna z config/projectly.yaml):
    get_new_tasks   -> get_project_tasks (status=todo, assigneeId=konto AI roli)
    update_status   -> update_task (status)
    post_comment    -> add_task_comment          (główny kanał dialogu)
    get_comments    -> get_task_comments         (odczyt decyzji człowieka)
    create_task     -> create_task + link_tasks  (powiązanie z zadaniem-rodzicem)
    set_feedback    -> update_task (feedback + actualHours + completedAt)
    publish_status  -> create/update_documentation (strona statusu per rola)
    list_tasks      -> get_project_tasks
"""

import json
import os
from pathlib import Path

import yaml

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem PROJECTLY_API_KEY
from mcp_client import MCPClient, MCPError

CONFIG_PATH = Path(__file__).parent / "config" / "projectly.yaml"
ROLE_CONFIG_PATH = Path(__file__).parent / "config" / "role.json"
MOCK_TASKS_PATH = Path(__file__).parent / "mock_data" / "sample_tasks.json"
MOCK_RUNS_DIR = Path(__file__).parent / "runs"
MAX_COMMENTS_PER_TASK = 200  # rotacja mock_comments.json — patrz post_comment

# Projectly zna tylko trzy statusy (todo|in_progress|done). Pipeline używa
# szerszego zestawu wewnętrznego (planning, needs_approval, queued...) — tu je
# mapujemy, żeby update_task nie dostał nieznanego statusu. Domyślnie in_progress.
_STATUS_TO_PROJECTLY = {
    "done": "done",
    "queued": "todo",
    "todo": "todo",
    "in_progress": "in_progress",
    "planning": "in_progress",
    "needs_approval": "in_progress",
}


def _load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_role():
    if ROLE_CONFIG_PATH.exists():
        try:
            return json.loads(ROLE_CONFIG_PATH.read_text(encoding="utf-8")).get("role", "dev")
        except (ValueError, OSError):
            return "dev"
    return "dev"


class ProjectlyClient:
    """Realna implementacja na MCP. Token/URL z env (PROJECTLY_API_KEY /
    PROJECTLY_BASE_URL), reguły biznesowe z config/projectly.yaml."""

    def __init__(self, api_key=None, base_url=None):
        self.api_key = api_key or os.environ.get("PROJECTLY_API_KEY")
        self.base_url = base_url or os.environ.get("PROJECTLY_BASE_URL")
        self._cfg = _load_config()
        self._role = _load_role()
        self._mcp = MCPClient(self.base_url, self.api_key)
        self._people_by_id = None      # id -> name
        self._people_by_name = None    # lower(name) -> id
        self._projects = None          # lista projektów z list_projects

    # --- Katalog osób i projektów (cache z list_projects) ---

    def _refresh_directory(self):
        data = self._mcp.call_tool("list_projects", {})
        people = data.get("people", []) if isinstance(data, dict) else []
        projects = data.get("projects", []) if isinstance(data, dict) else []
        self._people_by_id = {p["id"]: p.get("name", "") for p in people}
        self._people_by_name = {p.get("name", "").lower(): p["id"] for p in people}
        self._projects = projects

    def _ensure_directory(self):
        if self._people_by_id is None:
            self._refresh_directory()

    def _is_ai_account(self, name):
        ai = self._cfg.get("ai_account", {})
        if ai.get("by") == "type":
            return False  # gdy MCP wystawi 'type' — dołożyć obsługę tutaj
        prefix = ai.get("name_prefix", "AI - ")
        return bool(name) and name.startswith(prefix)

    def _own_account_id(self):
        self._ensure_directory()
        account_name = self._cfg.get("role_to_account", {}).get(self._role)
        if not account_name:
            return None
        return self._people_by_name.get(account_name.lower())

    def _resolve_person_id(self, alias_or_name):
        """Alias z config (pawel/bot/unassigned_pool) albo wprost nazwa osoby
        -> id osoby w Projectly. Zwraca None, gdy nieznana/celowo bez przypisania."""
        self._ensure_directory()
        aliases = self._cfg.get("people_aliases", {})
        name = aliases.get(alias_or_name, alias_or_name)
        if name == "self":
            account_name = self._cfg.get("role_to_account", {}).get(self._role, "")
            name = account_name
        if not name:
            return None
        return self._people_by_name.get(str(name).lower())

    def _project_id_by_name(self, project_name):
        self._ensure_directory()
        for p in self._projects:
            if p.get("name", "").lower() == str(project_name).lower():
                return p["id"]
        return None

    @staticmethod
    def _as_task_list(result):
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("tasks", [])
        return []

    def _map_task(self, raw, project_id):
        """Realny schemat Projectly -> kontrakt wewnętrzny (runner_loop czyta
        task_id/title/risk_level_hint; project_id potrzebny do create_task)."""
        fm = self._cfg.get("field_mapping", {})
        assignees = raw.get("assignees") or ([] if raw.get("assignedTo") is None else [raw["assignedTo"]])
        assignee_name = assignees[0].get("name") if assignees else None
        return {
            "task_id": raw.get("id"),
            "title": raw.get("title", ""),
            "description": raw.get("description", ""),
            "expected_result": raw.get(fm.get("expected_result", "goal")),
            "acceptance_criteria": raw.get(fm.get("acceptance_criteria", "effect")),
            "risk_level_hint": fm.get("default_risk_level_hint", "yellow"),
            "status": raw.get("status"),
            "priority": raw.get("priority"),
            "due_date": raw.get("dueDate"),
            "estimated_hours": raw.get("estimatedHours"),
            "actual_hours": raw.get("actualHours"),
            "feedback": raw.get("feedback"),
            "completed_at": raw.get("completedAt"),
            "stage_id": (raw.get("stage") or {}).get("id"),
            "assignee": assignee_name,
            "project_id": project_id,
        }

    def _pollable_projects(self):
        self._ensure_directory()
        wanted = set(self._cfg.get("poll", {}).get("project_statuses", ["active"]))
        return [p for p in self._projects if p.get("status") in wanted]

    # --- Metody kontraktu (jak MockProjectlyClient) ---

    def get_new_tasks(self):
        """MCP: get_project_tasks. Zadania status=todo przypisane do konta AI
        tej roli, po wszystkich pollowanych projektach (filtr assigneeId po
        stronie serwera)."""
        own_id = self._own_account_id()
        if not own_id:
            account = self._cfg.get("role_to_account", {}).get(self._role, "?")
            print(f"[Projectly] Brak konta AI '{account}' dla roli '{self._role}' — nie pobieram zadań (fail-closed).")
            return []
        task_status = self._cfg.get("poll", {}).get("task_status", "todo")
        tasks = []
        for project in self._pollable_projects():
            result = self._mcp.call_tool(
                "get_project_tasks",
                {"projectId": project["id"], "status": task_status, "assigneeId": own_id},
            )
            for raw in self._as_task_list(result):
                tasks.append(self._map_task(raw, project["id"]))
        return tasks

    def post_comment(self, task_id, text):
        """MCP: add_task_comment. Główny kanał komunikacji z człowiekiem."""
        self._mcp.call_tool("add_task_comment", {"taskId": task_id, "body": text})
        return True

    def get_comments(self, task_id):
        """MCP: get_task_comments. Zwraca listę treści komentarzy (chronologicznie)
        — human_response_validator parsuje z nich decyzję człowieka."""
        result = self._mcp.call_tool("get_task_comments", {"taskId": task_id})
        comments = result.get("comments", []) if isinstance(result, dict) else []
        return [c.get("body", "") if isinstance(c, dict) else c for c in comments]

    def update_status(self, task_id, status):
        """MCP: update_task. Mapuje status wewnętrzny (planning/needs_approval/...)
        na status Projectly (todo|in_progress|done) — Projectly zna tylko te trzy."""
        projectly_status = _STATUS_TO_PROJECTLY.get(status, "in_progress")
        self._mcp.call_tool("update_task", {"taskId": task_id, "status": projectly_status})
        return True

    def default_admin_project_id(self):
        """project_id dla zadań bez naturalnego projektu źródłowego (alerty
        system_health_monitor.py, naprawcze kacper_monitor.py) — config
        default_admin_project (nazwa), rozwiązywana jak każda inna nazwa
        projektu. None, gdy nieskonfigurowany albo nierozpoznany (wywołujący
        wtedy nie twory zadania w Projectly, tylko loguje/publikuje status)."""
        name = self._cfg.get("default_admin_project")
        return self._project_id_by_name(name) if name else None

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None, relation_type="eskalacja"):
        """MCP: create_task (+ link_tasks). Tworzy zadanie w projekcie project_id,
        przypisane do assigned_to (alias lub nazwa osoby), i — jeśli podano
        parent_task_id — łączy je z rodzicem relacją relation_type (buduje ciąg
        oryginał->eskalacja->kontynuacja, PLAN-WDROZENIA.md sekcja 4)."""
        if not project_id:
            raise MCPError(
                "create_task wymaga project_id (Projectly tworzy zadanie w konkretnym projekcie). "
                "Zadania z get_new_tasks niosą 'project_id' — przekaż je z zadania źródłowego."
            )
        assignee_id = self._resolve_person_id(assigned_to)
        args = {
            "projectId": project_id,
            "title": title,
            "description": description,
            "assigneeIds": [assignee_id] if assignee_id else [],
        }
        result = self._mcp.call_tool("create_task", args)
        new_id = result.get("id") if isinstance(result, dict) else None
        if not new_id and isinstance(result, dict):
            new_id = (result.get("task") or {}).get("id")
        if parent_task_id and new_id:
            self._mcp.call_tool(
                "link_tasks",
                {"fromTaskId": parent_task_id, "toTaskId": new_id, "type": relation_type},
            )
        return new_id

    def set_task_feedback(self, task_id, feedback=None, actual_hours=None, completed_at=None, status=None):
        """MCP: update_task. Feedback po zadaniu / samoocena i domknięcie:
        wypełnia feedback, realny czas (actualHours) i datę wykonania
        (completedAt), opcjonalnie ustawia status. Pola puste pomijamy."""
        args = {"taskId": task_id}
        if feedback is not None:
            args["feedback"] = feedback
        if actual_hours is not None:
            args["actualHours"] = actual_hours
        if completed_at is not None:
            args["completedAt"] = completed_at
        if status is not None:
            args["status"] = status
        self._mcp.call_tool("update_task", args)
        return True

    def get_task_relations(self, task_id):
        """MCP: get_task_relations. Powiązania w obu kierunkach (ciąg eskalacji)."""
        return self._mcp.call_tool("get_task_relations", {"taskId": task_id})

    def publish_status(self, role, payload):
        """MCP: create/update_documentation. Jeden, stały, nadpisywany wpis
        'status na żywo' per rola jako strona dokumentacji (PLAN-WDROZENIA.md
        sekcja 2). Degraduje się miękko: gdy live_status.project pusty lub
        niedostępny, tylko loguje i nie wywala runnera."""
        cfg = self._cfg.get("live_status", {})
        project_name = cfg.get("project")
        if not project_name:
            print(f"[Projectly] live_status.project pusty — status roli '{role}' tylko lokalnie: {payload}")
            return False
        try:
            project_id = self._project_id_by_name(project_name)
            if not project_id:
                print(f"[Projectly] Projekt statusu '{project_name}' nieznaleziony — pomijam publikację.")
                return False
            title = cfg.get("page_title_template", "Status na żywo — {role}").format(role=role)
            markdown = self._status_markdown(title, payload)
            docs = self._mcp.call_tool("get_documentation", {"projectId": project_id})
            page_id = self._find_page_id(docs, title)
            if page_id:
                self._mcp.call_tool("update_documentation", {"pageId": page_id, "contentMarkdown": markdown})
            else:
                self._mcp.call_tool(
                    "create_documentation",
                    {"projectId": project_id, "title": title, "contentMarkdown": markdown},
                )
            return True
        except MCPError as exc:
            print(f"[Projectly] Publikacja statusu nie powiodła się (nie blokuję runnera): {exc}")
            return False

    @staticmethod
    def _find_page_id(docs, title):
        pages = []
        if isinstance(docs, dict):
            pages = docs.get("pages", docs.get("documentation", []))
        elif isinstance(docs, list):
            pages = docs
        for page in pages:
            if isinstance(page, dict) and page.get("title", "").lower() == title.lower():
                return page.get("id")
        return None

    @staticmethod
    def _status_markdown(title, payload):
        lines = [f"# {title}", ""]
        for key, value in payload.items():
            lines.append(f"- **{key}**: {value}")
        return "\n".join(lines)

    def list_tasks(self, project_id=None, status=None):
        """MCP: get_project_tasks. Lista zadań (mapowana do kontraktu
        wewnętrznego) — dla jednego projektu lub wszystkich pollowanych."""
        projects = [{"id": project_id}] if project_id else self._pollable_projects()
        args_status = {"status": status} if status else {}
        tasks = []
        for project in projects:
            result = self._mcp.call_tool(
                "get_project_tasks", {"projectId": project["id"], **args_status}
            )
            for raw in self._as_task_list(result):
                tasks.append(self._map_task(raw, project["id"]))
        return tasks


class MockProjectlyClient:
    """Symuluje Projectly przy użyciu lokalnych plików JSON — do testowania
    Fazy 0-3 bez prawdziwego dostępu do API. Nowo utworzone zadania i status na
    żywo trafiają do runs/mock_*.json, żeby dało się je zweryfikować po przebiegu."""

    def __init__(self, tasks_path=MOCK_TASKS_PATH, project_tasks_path=None):
        self.tasks_path = tasks_path
        self.project_tasks_path = project_tasks_path or Path(__file__).parent / "mock_data" / "sample_project_tasks.json"
        self._created_tasks_path = MOCK_RUNS_DIR / "mock_created_tasks.json"
        self._comments_path = MOCK_RUNS_DIR / "mock_comments.json"
        self._live_status_path = MOCK_RUNS_DIR / "mock_live_status.json"
        self._feedback_path = MOCK_RUNS_DIR / "mock_feedback.json"

    def get_new_tasks(self):
        with open(self.tasks_path, encoding="utf-8") as f:
            return json.load(f)

    def post_comment(self, task_id, text):
        print(f"[MOCK Projectly] komentarz na {task_id}:\n{text}\n")
        comments = self._load(self._comments_path, default={})
        thread = comments.setdefault(task_id, [])
        thread.append(text)
        # Bez limitu ten plik rośnie bez końca, gdy scheduler w trybie mock
        # zostaje włączony na dłużej (żywy incydent: sample_tasks.json wraca jako
        # "nowe" co cykl, bo mock get_new_tasks nie znaczy zadań jako odebrane —
        # 2263 komentarze/dzień na jedno zadanie, 6+ MB). Trzymamy tylko ostatnie N.
        del thread[:-MAX_COMMENTS_PER_TASK]
        self._save(self._comments_path, comments)
        return True

    def update_status(self, task_id, status):
        print(f"[MOCK Projectly] {task_id} -> status: {status}")
        return True

    def default_admin_project_id(self):
        return "MOCK-ADMIN-PROJECT"

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None, relation_type="eskalacja"):
        tasks = self._load(self._created_tasks_path, default=[])
        new_id = f"PRJ-ESC-{len(tasks) + 1:04d}"
        record = {
            "task_id": new_id,
            "title": title,
            "description": description,
            "assigned_to": assigned_to,
            "parent_task_id": parent_task_id,
            "project_id": project_id,
            "relation_type": relation_type if parent_task_id else None,
        }
        tasks.append(record)
        self._save(self._created_tasks_path, tasks)
        print(f"[MOCK Projectly] utworzono zadanie {new_id} dla {assigned_to}: {title}")
        return new_id

    def get_comments(self, task_id):
        comments = self._load(self._comments_path, default={})
        return comments.get(task_id, [])

    def set_task_feedback(self, task_id, feedback=None, actual_hours=None, completed_at=None, status=None):
        record = {"feedback": feedback, "actual_hours": actual_hours, "completed_at": completed_at, "status": status}
        store = self._load(self._feedback_path, default={})
        store[task_id] = record
        self._save(self._feedback_path, store)
        print(f"[MOCK Projectly] feedback na {task_id}: {record}")
        return True

    def get_task_relations(self, task_id):
        return {"count": 0, "relations": []}

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
        """Wczytuje JSON, samoleczące się z uszkodzenia: dwa procesy scheduler
        potrafią zapisywać ten sam mock_*.json równocześnie (żywy incydent
        21.08.2026 na mock_comments.json — 'Extra data', runner_loop padał na
        każdym cyklu). Uszkodzony plik traktujemy jak brak pliku, nie wywalamy
        pętli agenta o zepsuty plik mocka."""
        if not path.exists():
            return default
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            print(f"[MOCK Projectly] {path.name} uszkodzony ({exc}) — reset do wartości domyślnej.")
            return default

    @staticmethod
    def _save(path, data):
        """Zapis atomowy (tmp + os.replace) — os.replace jest atomowy na Windows
        i POSIX, więc równoległy zapis drugiego procesu nigdy nie zastaje pliku
        w stanie połowicznie zapisanym (przyczyna uszkodzenia opisana w _load)."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + f".tmp{os.getpid()}")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)


def get_client():
    """Zwraca realnego klienta, jeśli PROJECTLY_API_KEY jest ustawiony w
    środowisku, inaczej mock — żeby runner_loop.py dało się uruchomić od razu,
    bez czekania na prawdziwe dane dostępowe."""
    api_key = os.environ.get("PROJECTLY_API_KEY")
    if api_key:
        return ProjectlyClient(api_key=api_key, base_url=os.environ.get("PROJECTLY_BASE_URL"))
    return MockProjectlyClient()
