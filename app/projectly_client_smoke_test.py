"""
Test dymny MockProjectlyClient._load/_save: samo-leczenie z uszkodzonego JSON
i rotacja mock_comments.json (żywy incydent 21.08.2026 — dwa procesy scheduler
pisały równocześnie do runs/mock_comments.json, plik narósł do 6+ MB i
uszkodził się, "Extra data" wywalało runner_loop na każdym cyklu). Operuje na
plikach TYMCZASOWYCH, nie dotyka prawdziwego runs/mock_comments.json.
"""

import json
import os
import tempfile
from pathlib import Path

import projectly_client
from projectly_client import MAX_COMMENTS_PER_TASK, MockProjectlyClient, ProjectlyClient


def _client_with(path):
    client = MockProjectlyClient()
    client._comments_path = path
    return client


def test_self_heal_from_corrupt_json():
    tmp = Path(tempfile.mkdtemp())
    bad = tmp / "mock_comments.json"
    bad.write_text('{"PRJ-0001": ["a"]} extra garbage', encoding="utf-8")

    client = _client_with(bad)
    assert client.get_comments("PRJ-0001") == [], "plik uszkodzony musi być traktowany jak brak danych"

    client.post_comment("PRJ-0001", "hello")
    data = json.loads(bad.read_text(encoding="utf-8"))
    assert data == {"PRJ-0001": ["hello"]}, "zapis po samo-leczeniu musi być czystym, poprawnym JSON"
    print("OK  odczyt uszkodzonego JSON nie wywala runnera, zapis go naprawia")


def test_atomic_save_no_leftover_tmp():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "mock_comments.json"
    client = _client_with(path)

    client.post_comment("X", "msg")
    leftovers = list(tmp.glob("*.tmp*"))
    assert leftovers == [], f"zapis atomowy nie powinien zostawiać plików tymczasowych: {leftovers}"
    print("OK  zapis atomowy (tmp + os.replace) nie zostawia plików tymczasowych")


def test_comments_rotate_and_cap():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "mock_comments.json"
    client = _client_with(path)

    total = MAX_COMMENTS_PER_TASK + 50
    for i in range(total):
        client.post_comment("X", f"msg{i}")

    thread = client.get_comments("X")
    assert len(thread) == MAX_COMMENTS_PER_TASK, f"lista powinna być przycięta do {MAX_COMMENTS_PER_TASK}, jest {len(thread)}"
    assert thread[0] == f"msg{total - MAX_COMMENTS_PER_TASK}", "musi zostać NAJNOWSZY ogon, nie początek"
    assert thread[-1] == f"msg{total - 1}"
    print(f"OK  komentarze przycięte do ostatnich {MAX_COMMENTS_PER_TASK} (bez nieograniczonego wzrostu pliku)")


def test_mock_has_default_admin_project_id():
    # ProjectlyClient.create_task realnego klienta wymaga project_id (żywy
    # incydent 21.08.2026 — kacper_monitor/system_health_monitor wywalały się
    # na tym przy zadaniach bez naturalnego projektu). Mock musi wystawiać ten
    # sam interfejs, żeby kod wywołujący był identyczny na mocku i na żywo.
    client = MockProjectlyClient()
    assert client.default_admin_project_id(), "mock musi zwracac niepusty project_id"
    print("OK  MockProjectlyClient.default_admin_project_id() zwraca stały mockowy id")


class _FakeMCPClient:
    """Wzorzec z live_status_publisher_smoke_test.py — CELOWO BEZ SIECI."""

    def __init__(self, create_task_id="CHILD-1"):
        self.calls = []
        self._create_task_id = create_task_id

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        if name == "create_task":
            return {"id": self._create_task_id}
        return {}


def test_create_task_subtask_of_sends_parent_task_id_not_zbot_link_tasks():
    # subtask_of/order to PRAWDZIWA hierarchia (Task.parentTaskId, commit 261
    # Projectly 24.08.2026) — inny mechanizm niż parent_task_id/relation_type
    # (TaskRelation przez zbot_link_tasks, eskalacja/kontynuacja).
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._mcp = _FakeMCPClient(create_task_id="CHILD-1")

    new_id = client.create_task("Podzadanie 1", "opis", assigned_to="bot",
                                subtask_of="PARENT-1", order=0, project_id="PROJ-1")

    assert new_id == "CHILD-1"
    names = [c[0] for c in client._mcp.calls]
    assert "zbot_link_tasks" not in names, "subtask_of nie powinno wołać zbot_link_tasks, tylko create_task"
    create_calls = [c for c in client._mcp.calls if c[0] == "create_task"]
    assert len(create_calls) == 1
    args = create_calls[0][1]
    assert args["parentTaskId"] == "PARENT-1"
    assert args["order"] == 0
    print("OK  create_task(subtask_of=..., order=...) wysyła parentTaskId/order w create_task, nie zbot_link_tasks")


def test_create_task_parent_task_id_still_uses_zbot_link_tasks():
    # Regresja: stary mechanizm (eskalacja/kontynuacja) MUSI zostać nietknięty.
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._mcp = _FakeMCPClient(create_task_id="CHILD-2")

    client.create_task("Eskalacja", "opis", assigned_to="pawel",
                       parent_task_id="ORIG-1", project_id="PROJ-1", relation_type="eskalacja")

    create_args = next(a for n, a in client._mcp.calls if n == "create_task")
    link_calls = [a for n, a in client._mcp.calls if n == "zbot_link_tasks"]
    assert len(link_calls) == 1, "parent_task_id musi wołać zbot_link_tasks jak dotychczas"
    assert link_calls[0] == {"fromTaskId": "ORIG-1", "toTaskId": "CHILD-2", "type": "eskalacja"}
    assert "parentTaskId" not in create_args, "bez subtask_of, create_task nie może wysłać parentTaskId"
    print("OK  create_task(parent_task_id=...) dalej woła zbot_link_tasks (eskalacja/kontynuacja nietknięte)")


def test_map_task_exposes_parent_task_id_and_subtask_count():
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    mapped_parent = client._map_task({"id": "T-1", "title": "Rodzic", "parentTaskId": None, "subtaskCount": 3},
                                     project_id="PROJ-1")
    mapped_child = client._map_task({"id": "T-2", "title": "Dziecko", "parentTaskId": "T-1", "subtaskCount": 0},
                                    project_id="PROJ-1")
    assert mapped_parent["parent_task_id"] is None and mapped_parent["subtask_count"] == 3
    assert mapped_child["parent_task_id"] == "T-1" and mapped_child["subtask_count"] == 0
    print("OK  _map_task mapuje parentTaskId/subtaskCount na parent_task_id/subtask_count")


def test_update_status_maps_przeniesione_literally():
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._mcp = _FakeMCPClient()

    client.update_status("T-1", "przeniesione")

    name, args = client._mcp.calls[0]
    assert name == "update_task"
    assert args["status"] == "przeniesione", "status przeniesione musi iść wprost, nie przez fallback in_progress"
    print("OK  update_status('przeniesione') mapuje na Projectly status 'przeniesione', nie in_progress")


def test_set_task_feedback_sends_cost_usd_to_update_task():
    # costUsd (29.08.2026, docs/MCP-STATUS-I-KOSZTY.md sekcja 2) - koszt PER
    # ZADANIE, rozbicie kosztow per agent jako suma jego zadan w Projectly.
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._mcp = _FakeMCPClient()

    client.set_task_feedback("T-1", feedback="Zrobione.", cost_usd=0.8765)

    name, args = client._mcp.calls[0]
    assert name == "update_task"
    assert args["costUsd"] == 0.8765, "cost_usd musi trafic jako costUsd (camelCase) do update_task"
    print("OK  set_task_feedback wysyla cost_usd jako costUsd do update_task")


def test_set_task_feedback_omits_cost_usd_when_not_given():
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._mcp = _FakeMCPClient()

    client.set_task_feedback("T-1", feedback="Zrobione.")

    _, args = client._mcp.calls[0]
    assert "costUsd" not in args, "brak cost_usd -> pole pominiete, nie None"
    print("OK  set_task_feedback bez cost_usd -> costUsd pominiete w wywolaniu MCP")


def test_load_role_bot_role_env_var_overrides_role_json(tmp_path=None):
    # BOT_ROLE dodane 29.08.2026 (ten sam mechanizm co env_bootstrap._current_role,
    # celowo zduplikowany zamiast importu - patrz komentarz przy _load_role) -
    # kilka procesow (dev/checker/marketing) na jednej maszynie nie moga
    # wspoldzielic jednego role.json bez wyscigu.
    original_path = projectly_client.ROLE_CONFIG_PATH
    tmp = Path(tempfile.mkdtemp()) / "role.json"
    tmp.write_text(json.dumps({"role": "dev"}), encoding="utf-8")
    projectly_client.ROLE_CONFIG_PATH = tmp
    original_env = os.environ.get("BOT_ROLE")
    os.environ["BOT_ROLE"] = "checker"
    try:
        assert projectly_client._load_role() == "checker"
    finally:
        projectly_client.ROLE_CONFIG_PATH = original_path
        if original_env is None:
            os.environ.pop("BOT_ROLE", None)
        else:
            os.environ["BOT_ROLE"] = original_env
    print("OK  _load_role(): BOT_ROLE w środowisku ma pierwszeństwo nad role.json")


if __name__ == "__main__":
    test_self_heal_from_corrupt_json()
    test_atomic_save_no_leftover_tmp()
    test_comments_rotate_and_cap()
    test_mock_has_default_admin_project_id()
    test_create_task_subtask_of_sends_parent_task_id_not_zbot_link_tasks()
    test_create_task_parent_task_id_still_uses_zbot_link_tasks()
    test_map_task_exposes_parent_task_id_and_subtask_count()
    test_update_status_maps_przeniesione_literally()
    test_set_task_feedback_sends_cost_usd_to_update_task()
    test_set_task_feedback_omits_cost_usd_when_not_given()
    test_load_role_bot_role_env_var_overrides_role_json()
    print("\nWszystkie testy MockProjectlyClient przeszły.")
