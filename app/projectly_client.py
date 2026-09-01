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
    publish_status  -> post_agent_status (dedykowany wiersz statusu per rola —
                       PLAN-MONITOROWANIE-AGENTOW-*.md; config: live_status.transport)
    list_tasks      -> get_project_tasks
"""

import json
import os
from pathlib import Path

import yaml
from dotenv import dotenv_values

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem PROJECTLY_API_KEY
from mcp_client import MCPClient, MCPError

CONFIG_PATH = Path(__file__).parent / "config" / "projectly.yaml"
ROLE_CONFIG_PATH = Path(__file__).parent / "config" / "role.json"
MOCK_TASKS_PATH = Path(__file__).parent / "mock_data" / "sample_tasks.json"
MOCK_RUNS_DIR = Path(__file__).parent / "runs"
MAX_COMMENTS_PER_TASK = 200  # rotacja mock_comments.json — patrz post_comment

# Pole "priority" (number) na zadaniu Projectly — 4 poziomy, znaczenie
# potwierdzone wprost w opisie schematu MCP create_task/update_task
# (tools/list, 29.08.2026), zgodne z decyzją właściciela o czterech kolumnach
# roboczych: parking (czeka na decyzję człowieka) / backlog (opcjonalne, może
# poczekać) / bieżące (normalna praca) / priorytet (najważniejsze, obsłużyć
# najpierw). runner_loop.py sortuje/dzieli kolejkę bota WYŁĄCZNIE po tym polu
# (patrz _efektywny_priorytet, PRIORITY_DEFAULT).
PRIORITY_PARKING = 0
PRIORITY_BACKLOG = 3
PRIORITY_BIEZACE = 4
PRIORITY_PRIORYTET = 5


def effective_priority(task, default=PRIORITY_BIEZACE):
    """Priorytet zadania z bezpiecznym fallbackiem na brak/nienumeryczną wartość.
    CELOWO NIE `task.get("priority") or default` — priority=0 (PARKING) jest
    falsy w Pythonie i taki zapis błędnie podbijałby zaparkowane zadanie do
    domyślnego priorytetu (żywy bug znaleziony 29.08.2026 w task_decomposer.py
    i escalation.py przy pisaniu tej funkcji)."""
    priorytet = task.get("priority")
    return priorytet if isinstance(priorytet, (int, float)) else default

# Projectly zna cztery statusy (todo|in_progress|done|przeniesione — ostatni to
# natywny status kontenera rozbitego na podzadania, potwierdzony przez właściciela
# Projectly 24.08.2026, patrz task_decomposer.py). Pipeline używa szerszego zestawu
# wewnętrznego (planning, needs_approval, queued...) — tu je mapujemy, żeby
# update_task nie dostał nieznanego statusu. Domyślnie in_progress.
_STATUS_TO_PROJECTLY = {
    "done": "done",
    "queued": "todo",
    "todo": "todo",
    "in_progress": "in_progress",
    "planning": "in_progress",
    "needs_approval": "in_progress",
    "przeniesione": "przeniesione",
}


def _load_config():
    if not CONFIG_PATH.exists():
        return {}
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_role():
    """BOT_ROLE ma pierwszeństwo nad config/role.json — patrz
    env_bootstrap._current_role() (kopia tej samej logiki, ten sam powód:
    kilka procesów na jednej maszynie/repo pod różnymi rolami bez
    współdzielenia jednego pliku)."""
    if os.environ.get("BOT_ROLE"):
        return os.environ["BOT_ROLE"]
    if ROLE_CONFIG_PATH.exists():
        try:
            return json.loads(ROLE_CONFIG_PATH.read_text(encoding="utf-8")).get("role", "dev")
        except (ValueError, OSError):
            return "dev"
    return "dev"


def own_account_name(role=None):
    """Nazwa konta AI Projectly (np. "AI - Dev", "AI-Checker") tej roli, wg
    config/projectly.yaml role_to_account — ta sama nazwa, jaką _map_task
    kładzie w polu 'assignee'. Do porównania "czy to zadanie jest MOJE"
    (task_feedback_requester.py, escalation_watcher.py) — bot ma czytać/
    działać wyłącznie na zadaniach przypisanych do WŁASNEGO konta, nigdy
    cudzych (ludzi albo innych botów). Funkcja modułowa, nie metoda klienta —
    nie wymaga instancji ProjectlyClient/MockProjectlyClient (mock nie ma
    self._role), więc działa identycznie w obu trybach."""
    role = role or _load_role()
    return _load_config().get("role_to_account", {}).get(role)


_STATUS_ENUM = {"working", "idle", "alert", "paused", "stopped"}
# snake_case (jak build_status() i inni wywolujacy publish_status) -> kontrakt
# post_agent_status (camelCase, PLAN-MONITOROWANIE-AGENTOW-*.md sekcja 1).
_STATUS_KEY_RENAME = {
    "current_task_id": "currentTaskId",
    "current_task_title": "currentTaskTitle",
    "progress_label": "progressLabel",
    "queue_depth": "queueDepth",
    "needs_approval_count": "needsApprovalCount",
    "cost_today_usd": "costTodayUsd",
    "cost_limit_usd": "costLimitUsd",
    "machine": "machine",
    "message": "message",
    # Dodane 29.08.2026 (docs/MCP-STATUS-I-KOSZTY.md sekcja 1) — dłuższy opis
    # zdarzenia (co dokładnie się wydarzyło, ID, parametry), pokazywany po
    # rozwinięciu zdarzenia w monitoringu Projectly. Odrębne od `details`
    # (liczba mnoga, cały surowy payload, niżej) — `detail` to CELOWY, krótki
    # tekst pisany PRZEZ wywołującego (patrz live_status_publisher.build_status
    # nowy parametr `detail`), nie automatyczny zrzut.
    "detail": "detail",
    # Dodane 25.08.2026 — jak "details" niżej: produkcyjny schemat post_agent_status
    # może dziś TO pole ignorować (nierozpoznany klucz), wysyłamy mimo to, żeby
    # zadziałało bez zmiany tego kodu, gdy Projectly rozpozna je po swojej stronie.
    # Cel: freshness/"online" liczona wobec RZECZYWISTEGO interwału tej roli, nie
    # jednego globalnego progu (żywy incydent 25.08.2026 — machine-status,
    # interwał 3600s, wyglądał na "offline" pod progiem myślanym dla ról 30-120s).
    "update_interval_seconds": "updateIntervalSeconds",
}


def _map_status_payload(payload):
    """Normalizuje DOWOLNY payload przekazany do publish_status(role, payload)
    do kontraktu narzędzia MCP post_agent_status (PLAN-MONITOROWANIE-AGENTOW-*.md
    sekcja 1). Cztery wywołujące (live_status_publisher, machine_status_reporter,
    kacper_monitor, system_health_monitor) budują dziś CZTERY różne kształty
    słownika — ta funkcja jest jedynym miejscem, które je pojednuje, więc żaden
    z nich nie wymaga zmiany kodu.

    Zasada: rozpoznane pola trafiają na wierzch (UI renderuje je specjalnie),
    ale 'details' zawsze niesie CAŁY oryginalny payload bez strat — nic, czego
    ta funkcja nie rozpozna, nie ginie."""
    mapped = {}
    for src_key, dst_key in _STATUS_KEY_RENAME.items():
        if src_key in payload and payload[src_key] is not None:
            mapped[dst_key] = payload[src_key]

    # health: "ok"/"alert" wprost jeśli już w tym kształcie (live_status_publisher).
    # Inaczej wnioskujemy z 'status' o znaczeniu health (system_health_monitor:
    # ok/warning/critical) — fail-closed: niepewne/nierozpoznane traktujemy jako
    # alert, nie ukrywamy problemu za zielonym statusem.
    raw_health = payload.get("health")
    raw_status_field = payload.get("status")
    if raw_health in ("ok", "alert"):
        mapped["health"] = raw_health
    elif raw_status_field in ("critical", "warning", "error", "alert"):
        mapped["health"] = "alert"
    elif raw_status_field == "ok":
        mapped["health"] = "ok"
    else:
        mapped["health"] = "ok"

    issues = payload.get("issues")
    if issues:
        mapped["healthDetail"] = "; ".join(str(i) for i in issues) if isinstance(issues, list) else str(issues)

    # status (aktywnosc bota: working/idle/alert/paused/stopped) - NIE to samo co
    # health powyzej. Tylko live_status_publisher uzywa tego pola w tym sensie;
    # role pomocnicze (machine-status/monitoring/system-health) dostaja domyslnie
    # "idle", bo ich wlasne 'status'/'health' znaczy cos innego (patrz wyzej).
    mapped["status"] = raw_status_field if raw_status_field in _STATUS_ENUM else "idle"

    # 'message' i 'health' nie zawsze da się wywnioskować generycznie (wyżej). Dla dwóch
    # znanych kształtów bez własnego pola message/health (machine_status_reporter.py,
    # kacper_monitor.py) budujemy krótkie, czytelne podsumowanie — narzędzie MCP
    # post_agent_status na produkcji (stan na 2026-08-22) NIE ma pola 'details' (worek na
    # resztę danych, zakładany w PLAN-MONITOROWANIE-AGENTOW-PROJECTLY.md), więc bez tego te
    # dwie role trafiałyby do dashboardu jako puste wiersze.
    if "message" not in mapped and "tool_versions" in payload:
        versions = payload.get("tool_versions") or {}
        parts = [f"{name}: {value or '?'}" for name, value in versions.items()]
        ram = payload.get("ram_available_percent")
        if ram is not None:
            parts.append(f"RAM wolne: {ram}%")
        if parts:
            mapped["message"] = " | ".join(parts)

    if "message" not in mapped and "repair_tasks_created" in payload:
        repairs = payload.get("repair_tasks_created") or []
        scanned = payload.get("events_scanned")
        mapped["message"] = f"Przeskanowano {scanned} zdarzeń, utworzono {len(repairs)} zadań naprawczych"
        if repairs:
            mapped["health"] = "alert"

    # Trzeci znany kształt bez własnego message: live_status_publisher.py
    # (queued_tasks/processed_this_cycle). Bez syntezy queueDepth widać jako
    # liczba, ale KTÓRE to zadania (tytuł/id, o co user prosił 24.08.2026)
    # ginęłoby w 'details', które produkcja dziś ignoruje.
    if "message" not in mapped and "queued_tasks" in payload:
        def _etykieta(t):
            return str(t.get("title") or t.get("task_id") or "?")[:60]

        processed = payload.get("processed_this_cycle") or []
        queued = payload.get("queued_tasks") or []
        parts = []
        if processed:
            parts.append("Ostatnio wykonane: " + ", ".join(_etykieta(t) for t in processed))
        if queued:
            est = payload.get("estimated_minutes_to_clear_queue")
            czas = f", ~{est} min" if est else ""
            parts.append(f"W kolejce ({len(queued)}{czas}): " + ", ".join(_etykieta(t) for t in queued))
        else:
            parts.append("Kolejka pusta")
        mapped["message"] = (" | ".join(parts))[:500]

    # 'details' wysyłamy mimo braku pola w dzisiejszym schemacie produkcyjnym: zod domyślnie
    # ignoruje nierozpoznane klucze (potwierdzone testem na żywo), więc to nieszkodliwe —
    # a gdy Projectly doda pole 'details', zacznie działać bez zmiany tego kodu.
    mapped["details"] = payload
    return mapped


class ProjectlyClient:
    """Realna implementacja na MCP. Token/URL z env (PROJECTLY_API_KEY /
    PROJECTLY_BASE_URL), reguły biznesowe z config/projectly.yaml."""

    def __init__(self, api_key=None, base_url=None, role=None):
        """`role` jawne (01.09.2026) — dotąd rola klienta brała się WYŁĄCZNIE ze
        zmiennej BOT_ROLE tego procesu, więc jeden proces mógł rozmawiać z
        Projectly tylko jako jedna rola. agent_supervisor.py musi odpytać
        wszystkie cztery role naraz (każda ma własny token i własny projekt
        administracyjny — patrz default_admin_project_by_role), więc buduje
        klienta per rola przez client_for_role(). role=None zachowuje
        dotychczasowe zachowanie co do znaku."""
        self.api_key = api_key or os.environ.get("PROJECTLY_API_KEY")
        self.base_url = base_url or os.environ.get("PROJECTLY_BASE_URL")
        self._cfg = _load_config()
        self._role = role or _load_role()
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

    def _polled_account_names(self):
        """Konta AI, których zadania bierze TA maszyna: własne konto roli plus
        konta z poll.extra_accounts. Do 29.08.2026 rola 'dev' fizycznie
        wykonywała też zadania marketingowe (extra_accounts zawierał
        'AI - Marketing') — od tej daty marketing ma WŁASNY, osobny proces
        (BOT_ROLE=marketing), więc jego konto zostało stąd usunięte (dwa
        procesy pytające o to samo konto ryzykowałyby podwójne wykonanie).
        extra_accounts zostaje jako mechanizm na wypadek przyszłych ról bez
        własnego procesu — zadanie wrzucone na konto spoza własnej roli I
        spoza tej listy po cichu wisiałoby w kolejce, nigdy niepodjęte."""
        wlasne = self._cfg.get("role_to_account", {}).get(self._role)
        nazwy = [wlasne] if wlasne else []
        for dodatkowe in self._cfg.get("poll", {}).get("extra_accounts", []) or []:
            if dodatkowe and dodatkowe not in nazwy:
                nazwy.append(dodatkowe)
        return nazwy

    def _polled_account_ids(self):
        """(nazwa, id) dla kont do pollowania. Konto wymienione w configu, ale
        nieistniejące w Projectly, jest RAPORTOWANE, nie pomijane po cichu —
        literówka w nazwie inaczej wygląda dokładnie jak 'brak zadań'."""
        self._ensure_directory()
        pary, brakujace = [], []
        for nazwa in self._polled_account_names():
            konto_id = self._people_by_name.get(nazwa.lower())
            if konto_id:
                pary.append((nazwa, konto_id))
            else:
                brakujace.append(nazwa)
        if brakujace:
            print("[Projectly] Kont AI z configu nie ma w Projectly: %s — zadania z tych kont NIE będą "
                  "pobierane. Sprawdź pisownię w config/projectly.yaml." % ", ".join(brakujace))
        return pary

    def _resolve_person_id(self, alias_or_name):
        """Alias z config (pawel/bot/unassigned_pool) albo wprost nazwa osoby
        -> id osoby w Projectly. Zwraca None w dwóch różnych sytuacjach:
        - celowo bez przypisania (np. unassigned_pool mapuje się na "") — cicho,
          to zamierzone zachowanie;
        - nazwa nierozpoznana w katalogu Projectly (literówka, rozjazd nazw) —
          GŁOŚNO, bo inaczej create_task tworzy zadanie z assigneeIds=[],
          niewidoczne dla człowieka, bez żadnego śladu w logach (żywy,
          niezdiagnozowany do końca incydent 23.08.2026 — eskalacje lądowały
          bez przypisania; to jeden z podejrzanych mechanizmów)."""
        self._ensure_directory()
        aliases = self._cfg.get("people_aliases", {})
        name = aliases.get(alias_or_name, alias_or_name)
        if name == "self":
            account_name = self._cfg.get("role_to_account", {}).get(self._role, "")
            name = account_name
        if not name:
            return None
        person_id = self._people_by_name.get(str(name).lower())
        if person_id is None:
            print(f"[projectly_client] Nie znaleziono osoby '{name}' (wejście: '{alias_or_name}') w katalogu "
                  f"Projectly — zadanie zostanie utworzone BEZ przypisania (assigneeIds=[]), niewidoczne dla "
                  f"człowieka. Sprawdź pisownię nazwy w Projectly albo w config/projectly.yaml (people_aliases "
                  f"/ role_to_account / escalation_default_assignee).")
        return person_id

    def _project_id_by_name(self, project_name):
        self._ensure_directory()
        for p in self._projects:
            if p.get("name", "").lower() == str(project_name).lower():
                return p["id"]
        return None

    def project_name(self, project_id):
        """Odwrotność _project_id_by_name — nazwa projektu po id, do kontekstu
        promptu subagenta (agentic_worker.py). Fail-soft: brak/nieznany id -> None."""
        if not project_id:
            return None
        self._ensure_directory()
        for p in self._projects:
            if p.get("id") == project_id:
                return p.get("name")
        return None

    def list_projects_with_stages(self):
        """Wszystkie projekty widoczne temu kontu, z listą etapów (id+name) —
        do context_cache.py (decyzja właściciela 30.08.2026: boty oceniające i
        subagenci mają zawsze znać projekt I ETAP zadania, nie tylko treść).
        list_projects zwraca to już w surowym kształcie, tu tylko czytelny
        podzbiór pól (id/name/stages)."""
        self._ensure_directory()
        return [{"id": p.get("id"), "name": p.get("name"), "stages": p.get("stages", [])}
               for p in self._projects]

    def get_knowledge_base(self):
        """MCP: zbot_get_knowledge_base — WSZYSTKIE wpisy bazy wiedzy widoczne
        temu kontu (scope 'self' własne + 'general' firmowe). Do context_cache.py
        (odświeżane rzadko, nie przy każdym zadaniu — patrz tamten moduł)."""
        result = self._mcp.call_tool("zbot_get_knowledge_base", {})
        return result if isinstance(result, dict) else {"entries": []}

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
            "parent_task_id": raw.get("parentTaskId"),
            "subtask_count": raw.get("subtaskCount", 0),
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
        konta = self._polled_account_ids()
        if not konta:
            account = self._cfg.get("role_to_account", {}).get(self._role, "?")
            print(f"[Projectly] Brak konta AI '{account}' dla roli '{self._role}' — nie pobieram zadań (fail-closed).")
            return []
        task_status = self._cfg.get("poll", {}).get("task_status", "todo")
        tasks = []
        widziane = set()
        for project in self._pollable_projects():
            for nazwa_konta, konto_id in konta:
                result = self._mcp.call_tool(
                    "get_project_tasks",
                    {"projectId": project["id"], "status": task_status, "assigneeId": konto_id},
                )
                for raw in self._as_task_list(result):
                    # To samo zadanie może wyjść z dwóch kont (współprzypisanie) —
                    # bez odsiania runner wykonałby je dwa razy.
                    if raw.get("id") in widziane:
                        continue
                    widziane.add(raw.get("id"))
                    zadanie = self._map_task(raw, project["id"])
                    zadanie["ai_account"] = nazwa_konta
                    tasks.append(zadanie)
        return tasks

    def post_comment(self, task_id, text):
        """MCP: zbot_add_task_comment. Główny kanał komunikacji z człowiekiem."""
        self._mcp.call_tool("zbot_add_task_comment", {"taskId": task_id, "body": text})
        return True

    def get_comments(self, task_id):
        """MCP: zbot_get_task_comments. Zwraca listę treści komentarzy (chronologicznie)
        — human_response_validator parsuje z nich decyzję człowieka."""
        result = self._mcp.call_tool("zbot_get_task_comments", {"taskId": task_id})
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
        system_health_monitor.py, naprawcze kacper_monitor.py, kontrolne
        remote_control.py) — config default_admin_project (nazwa), rozwiązywana
        jak każda inna nazwa projektu. None, gdy nieskonfigurowany albo
        nierozpoznany (wywołujący wtedy nie twory zadania w Projectly, tylko
        loguje/publikuje status).

        default_admin_project_by_role (29.08.2026) ma pierwszeństwo dla TEJ
        roli — różne konta AI mają różny zakres widocznych projektów (np.
        "AI-Checker" nie widzi "Administracyjne", tylko "Usprawnienia"),
        więc jedna globalna nazwa nie mogła wystarczyć wszystkim rolom."""
        name = self._cfg.get("default_admin_project_by_role", {}).get(self._role) \
            or self._cfg.get("default_admin_project")
        return self._project_id_by_name(name) if name else None

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None,
                    relation_type="eskalacja", expected_result=None, acceptance_criteria=None,
                    subtask_of=None, order=None, due_date=None, priority=None):
        """MCP: create_task (+ zbot_link_tasks). Tworzy zadanie w projekcie project_id,
        przypisane do assigned_to (alias lub nazwa osoby), i — jeśli podano
        parent_task_id — łączy je z rodzicem relacją relation_type (buduje ciąg
        oryginał->eskalacja->kontynuacja, PLAN-WDROZENIA.md sekcja 4).

        `subtask_of`/`order` to INNY mechanizm niż `parent_task_id`/`relation_type` —
        prawdziwa hierarchia rodzic->dziecko (Task.parentTaskId, widoczna w UI jako
        "Podzadania" i w get_project_tasks jako parentTaskId/subtaskCount), nie
        powiązanie TaskRelation. Potwierdzone przez właściciela Projectly 24.08.2026
        (commit 261) — patrz task_decomposer.py. `parent_task_id`/`relation_type`
        i `subtask_of`/`order` mogą być użyte niezależnie, nawet oba naraz, choć
        w praktyce dziś nic tego nie robi.

        expected_result/acceptance_criteria (pola Projectly: goal/effect, patrz
        field_mapping w config/projectly.yaml) — BEZ NICH bramka jakości (Oskar)
        ocenia efekt względem pustego oczekiwania, co daje niespójne,
        czasem fałszywie negatywne werdykty (realnie napotkane: zadanie testowe
        bez 'goal' dostało odrzucenie wizualne na poprawnym zrzucie)."""
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
        if expected_result is not None:
            args["goal"] = expected_result
        if acceptance_criteria is not None:
            args["effect"] = acceptance_criteria
        if due_date is not None:
            # Potwierdzone schematem MCP create_task (tools/list, 29.08.2026):
            # dueDate to udokumentowany, przyjmowany parametr zapisu.
            args["dueDate"] = due_date
        if priority is not None:
            # Priorytet: 0=parking, 3=backlog, 4=bieżące, 5=priorytet (dokładny
            # opis pola w schemacie MCP create_task/update_task, potwierdzone
            # 29.08.2026 — patrz stałe PRIORITY_* w tym module). Decyzja
            # właściciela: kolejka runnera ma sama sortować/priorytetyzować
            # zadania po tym polu, więc KAŻDE zadanie tworzone przez ten kod
            # (eskalacja, dekompozycja, alert, feedback...) ma je ustawiać
            # jawnie, zamiast zostawiać nieskonfigurowane (co Projectly
            # traktuje jako None -> _efektywny_priorytet() w runner_loop.py
            # spada na PRIORITY_DEFAULT).
            args["priority"] = priority
        if subtask_of is not None:
            args["parentTaskId"] = subtask_of
            if order is not None:
                args["order"] = order
        result = self._mcp.call_tool("create_task", args)
        new_id = result.get("id") if isinstance(result, dict) else None
        if not new_id and isinstance(result, dict):
            new_id = (result.get("task") or {}).get("id")
        if parent_task_id and new_id:
            self._mcp.call_tool(
                "zbot_link_tasks",
                {"fromTaskId": parent_task_id, "toTaskId": new_id, "type": relation_type},
            )
        return new_id

    def set_task_feedback(self, task_id, feedback=None, actual_hours=None, completed_at=None,
                          status=None, cost_usd=None):
        """MCP: update_task. Feedback po zadaniu / samoocena i domknięcie:
        wypełnia feedback, realny czas (actualHours) i datę wykonania
        (completedAt), opcjonalnie ustawia status. Pola puste pomijamy.

        cost_usd (NOWE, 29.08.2026 — docs/MCP-STATUS-I-KOSZTY.md sekcja 2):
        koszt AI TEGO zadania (`costUsd` w Projectly) — pole opcjonalne w MCP,
        jeszcze bez gwarancji zapisu po stronie serwera na czas wdrożenia
        (dokumentacja: "wchodzi do bazy przy najbliższym deployu... do tego
        czasu wysyłanie nie zaszkodzi"), więc wysyłamy mimo to — fail-soft."""
        args = {"taskId": task_id}
        if feedback is not None:
            args["feedback"] = feedback
        if actual_hours is not None:
            args["actualHours"] = actual_hours
        if completed_at is not None:
            args["completedAt"] = completed_at
        if status is not None:
            args["status"] = status
        if cost_usd is not None:
            args["costUsd"] = round(cost_usd, 4)
        self._mcp.call_tool("update_task", args)
        return True

    def get_task_relations(self, task_id):
        """MCP: zbot_get_task_relations. Powiązania w obu kierunkach (ciąg eskalacji)."""
        return self._mcp.call_tool("zbot_get_task_relations", {"taskId": task_id})

    def publish_status(self, role, payload):
        """Status na żywo per rola-w-koncie (PLAN-MONITOROWANIE-AGENTOW-*.md).
        Transport wybierany przez config/projectly.yaml -> live_status.transport:
        - "agent_status_tool" (docelowy): MCP zbot_post_agent_status — jeden nadpisywany
          wiersz (userId z tokenu, roleLabel=role) + wpis w historii zdarzeń.
        - "documentation" (domyślny, dopóki narzędzie MCP nie jest potwierdzone
          na produkcji Projectly): stare zachowanie — strona dokumentacji per rola.
        Oba warianty degradują się miękko: błąd MCP tylko loguje, nie wywala runnera."""
        cfg = self._cfg.get("live_status", {})
        transport = cfg.get("transport", "documentation")
        if transport == "agent_status_tool":
            return self._publish_status_via_tool(role, payload)
        return self._publish_status_via_documentation(role, payload, cfg)

    def _publish_status_via_tool(self, role, payload):
        """MCP: zbot_post_agent_status. Transport docelowy — patrz publish_status()."""
        try:
            args = {"roleLabel": role, **_map_status_payload(payload)}
            self._mcp.call_tool("zbot_post_agent_status", args)
            return True
        except MCPError as exc:
            print(f"[Projectly] Publikacja statusu (zbot_post_agent_status) nie powiodła się (nie blokuję runnera): {exc}")
            return False

    def _publish_status_via_documentation(self, role, payload, cfg):
        """MCP: create/update_documentation. Transport legacy — jedna, nadpisywana
        strona statusu per rola. Zachowany na czas przejścia (config
        live_status.transport); do usunięcia po potwierdzeniu post_agent_status
        na produkcji (PLAN-MONITOROWANIE-AGENTOW-WIRTUALNY-PRACOWNIK.md sekcja 3)."""
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

    def get_week_report(self, week_offset=0):
        """MCP: get_week_report. Co wykonano (po completedAt), statystyki per
        osoba, blokery/po terminie, odchylenie estymacji — ze WSZYSTKICH
        dostępnych kontu tokenu projektów. week_offset: 0=bieżący tydzień,
        -1=poprzedni, itd. Używane przez knowledge_digest_publisher.py."""
        return self._mcp.call_tool("get_week_report", {"weekOffset": week_offset})

    def create_knowledge(self, title, content, scope="self", tags=None, links=None):
        """MCP: zbot_create_knowledge. scope: "self" (własne konto, domyślne),
        "general" (firmowa — wymaga pełnego dostępu, master/admin) albo ID
        konta bota (jw). Zwraca dict z "id" nowego wpisu."""
        args = {"title": title, "content": content, "scope": scope}
        if tags is not None:
            args["tags"] = tags
        if links is not None:
            args["links"] = links
        return self._mcp.call_tool("zbot_create_knowledge", args)

    def update_knowledge(self, knowledge_id, title=None, content=None, tags=None, links=None):
        """MCP: zbot_update_knowledge. Podaj tylko pola do zmiany — content
        ZASTĘPUJE całość, nie scala."""
        args = {"knowledgeId": knowledge_id}
        if title is not None:
            args["title"] = title
        if content is not None:
            args["content"] = content
        if tags is not None:
            args["tags"] = tags
        if links is not None:
            args["links"] = links
        return self._mcp.call_tool("zbot_update_knowledge", args)


class MockProjectlyClient:
    """Symuluje Projectly przy użyciu lokalnych plików JSON — do testowania
    Fazy 0-3 bez prawdziwego dostępu do API. Nowo utworzone zadania i status na
    żywo trafiają do runs/mock_*.json, żeby dało się je zweryfikować po przebiegu."""

    def __init__(self, tasks_path=MOCK_TASKS_PATH, project_tasks_path=None):
        self.tasks_path = tasks_path
        self.project_tasks_path = project_tasks_path or Path(__file__).parent / "mock_data" / "sample_project_tasks.json"
        self._created_tasks_path = MOCK_RUNS_DIR / "mock_created_tasks.json"
        self._comments_path = MOCK_RUNS_DIR / "mock_comments.json"
        self._agent_status_path = MOCK_RUNS_DIR / "mock_agent_status.json"
        self._feedback_path = MOCK_RUNS_DIR / "mock_feedback.json"
        self._knowledge_path = MOCK_RUNS_DIR / "mock_knowledge.json"

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

    def project_name(self, project_id):
        """Mock: brak katalogu projektów lokalnie — tylko oznaczenie, że to
        jest ID projektu mock, żeby test_build_prompt mógł pokryć tę ścieżkę."""
        return f"[mock] {project_id}" if project_id else None

    def list_projects_with_stages(self):
        """Mock: brak katalogu projektów/etapów lokalnie — pusta lista (fail-soft
        w context_cache.py, nie ma czego udawać bez fixture)."""
        return []

    def get_knowledge_base(self):
        """Mock: brak bazy wiedzy lokalnie — pusty kształt kontraktu."""
        return {"count": 0, "entries": []}

    def create_task(self, title, description, assigned_to, parent_task_id=None, project_id=None,
                    relation_type="eskalacja", expected_result=None, acceptance_criteria=None,
                    subtask_of=None, order=None, due_date=None, priority=None):
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
            "expected_result": expected_result,
            "acceptance_criteria": acceptance_criteria,
            "subtask_of": subtask_of,
            "order": order,
            "due_date": due_date,
            "priority": priority,
        }
        tasks.append(record)
        self._save(self._created_tasks_path, tasks)
        print(f"[MOCK Projectly] utworzono zadanie {new_id} dla {assigned_to}: {title}")
        return new_id

    def get_comments(self, task_id):
        comments = self._load(self._comments_path, default={})
        return comments.get(task_id, [])

    def set_task_feedback(self, task_id, feedback=None, actual_hours=None, completed_at=None,
                          status=None, cost_usd=None):
        record = {"feedback": feedback, "actual_hours": actual_hours, "completed_at": completed_at,
                 "status": status, "cost_usd": cost_usd}
        store = self._load(self._feedback_path, default={})
        store[task_id] = record
        self._save(self._feedback_path, store)
        print(f"[MOCK Projectly] feedback na {task_id}: {record}")
        return True

    def get_task_relations(self, task_id):
        return {"count": 0, "relations": []}

    def publish_status(self, role, payload):
        """Zapisuje w kształcie kontraktu post_agent_status (nie surowego
        payloadu), żeby tryb mock realnie testował ten sam schemat co
        produkcja (PLAN-MONITOROWANIE-AGENTOW-WIRTUALNY-PRACOWNIK.md sekcja 1)."""
        statuses = self._load(self._agent_status_path, default={})
        statuses[role] = {"roleLabel": role, **_map_status_payload(payload)}
        self._save(self._agent_status_path, statuses)
        print(f"[MOCK Projectly] status na żywo ({role}): {statuses[role]}")
        return True

    def list_tasks(self, project_id=None, status=None):
        tasks = self._load(self.project_tasks_path, default=[])
        if project_id:
            tasks = [t for t in tasks if t.get("project_id") == project_id]
        if status:
            tasks = [t for t in tasks if t.get("status") == status]
        return tasks

    def get_week_report(self, week_offset=0):
        """Mock: kształt minimalny, wystarczający do testów knowledge_digest_publisher.py
        bez sieci - nie odzwierciedla realnej logiki serwera (completedAt itd.)."""
        return {"weekOffset": week_offset, "completed": [], "byPerson": {}, "overdue": [], "estimationDeviation": None}

    def create_knowledge(self, title, content, scope="self", tags=None, links=None):
        entries = self._load(self._knowledge_path, default=[])
        new_id = f"KNOW-{len(entries) + 1:04d}"
        entries.append({"id": new_id, "title": title, "content": content, "scope": scope, "tags": tags, "links": links})
        self._save(self._knowledge_path, entries)
        print(f"[MOCK Projectly] baza wiedzy: utworzono '{title}' (scope={scope}) -> {new_id}")
        return {"id": new_id}

    def update_knowledge(self, knowledge_id, title=None, content=None, tags=None, links=None):
        entries = self._load(self._knowledge_path, default=[])
        for entry in entries:
            if entry["id"] == knowledge_id:
                if title is not None:
                    entry["title"] = title
                if content is not None:
                    entry["content"] = content
                if tags is not None:
                    entry["tags"] = tags
                if links is not None:
                    entry["links"] = links
                self._save(self._knowledge_path, entries)
                print(f"[MOCK Projectly] baza wiedzy: zaktualizowano {knowledge_id}")
                return {"id": knowledge_id}
        print(f"[MOCK Projectly] baza wiedzy: {knowledge_id} nie znaleziony")
        return {"id": knowledge_id}

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


def client_for_role(role, secrets_dir=None):
    """Klient rozmawiający z Projectly jako WSKAZANA rola, niezależnie od roli
    procesu — token czytany z `secrets/agents/<rola>/.env` (to samo miejsce,
    które env_bootstrap wstrzykuje do os.environ przy starcie bota, tu tylko
    czytane bez modyfikowania środowiska procesu; dotenv_values nie dotyka
    os.environ, więc cztery role nie nadpisują się nawzajem).

    Bez pliku/klucza dla roli zwraca mock — dokładnie jak get_client(), żeby
    agent_supervisor.py dało się uruchomić na świeżej maszynie bez sekretów.
    secrets_dir wstrzykiwalny (testowalność, bez dotykania prawdziwych
    sekretów)."""
    secrets_dir = Path(secrets_dir) if secrets_dir else Path(__file__).parent / "secrets"
    values = dotenv_values(secrets_dir / "agents" / role / ".env", encoding="utf-8")
    api_key = values.get("PROJECTLY_API_KEY")
    if api_key:
        return ProjectlyClient(api_key=api_key, base_url=values.get("PROJECTLY_BASE_URL"), role=role)
    return MockProjectlyClient()
