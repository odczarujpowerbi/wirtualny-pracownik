"""
Test dymny normalizacji statusu (projectly_client._map_status_payload) i
wyboru transportu w ProjectlyClient.publish_status
(PLAN-MONITOROWANIE-AGENTOW-WIRTUALNY-PRACOWNIK.md). Bez sieci: MCPClient
nie łączy się z niczym przy konstrukcji, call_tool jest podmieniane atrapą.
Wpina się automatycznie w self_check.py.
"""

from projectly_client import ProjectlyClient, _map_status_payload


def test_map_status_payload_keeps_known_fields_and_full_details():
    # Kształt jak live_status_publisher.build_status().
    payload = {
        "role": "dev",
        "current_task_id": "T-1",
        "queue_depth": 3,
        "needs_approval_count": 1,
        "cost_today_usd": 1.5,
        "cost_limit_usd": 20.0,
        "health": "ok",
    }
    mapped = _map_status_payload(payload)
    assert mapped["currentTaskId"] == "T-1"
    assert mapped["queueDepth"] == 3
    assert mapped["needsApprovalCount"] == 1
    assert mapped["costTodayUsd"] == 1.5
    assert mapped["costLimitUsd"] == 20.0
    assert mapped["health"] == "ok"
    assert mapped["status"] == "idle", "brak pola 'status' w payloadzie -> domyślnie idle"
    assert mapped["details"] == payload, "oryginalny payload musi przetrwać bez strat w 'details'"
    print("OK  live_status_publisher-kształt payloadu -> pola rozpoznane + details bez strat")


def test_map_status_payload_infers_alert_from_critical_health_status():
    # Kształt jak system_health_monitor.py: 'status' znaczy ok/warning/critical, NIE working/idle/...
    payload = {
        "ram_available_percent": 4,
        "status": "critical",
        "issues": ["RAM poniżej progu", "proces X nie żyje"],
    }
    mapped = _map_status_payload(payload)
    assert mapped["health"] == "alert", "status='critical' (system_health_monitor) musi zmapować się na health='alert'"
    assert "RAM poniżej progu" in mapped["healthDetail"]
    assert mapped["status"] == "idle", "'critical' nie jest wartością enuma status (working/idle/...), fallback idle"
    print("OK  system_health_monitor-kształt (status=critical) -> health=alert, fail-closed")


def test_map_status_payload_unknown_shape_still_preserved_in_details():
    # Kształt jak kacper_monitor.py, BEZ zadań naprawczych (dzień bez problemów).
    payload = {
        "events_scanned": 7,
        "repair_tasks_created": [],
        "checked_at": "2026-08-22T10:00:00Z",
    }
    mapped = _map_status_payload(payload)
    assert mapped["health"] == "ok", "brak zadań naprawczych -> ok"
    assert mapped["status"] == "idle"
    assert "Przeskanowano 7 zdarzeń" in mapped["message"]
    assert mapped["details"] == payload
    print("OK  kacper_monitor-kształt (bez zadań naprawczych) -> health ok, message z podsumowaniem, details kompletne")


def test_map_status_payload_kacper_repairs_created_forces_alert_and_message():
    # Produkcyjny post_agent_status (stan 2026-08-22) NIE ma pola 'details' — bez syntezy
    # message ten wiersz w dashboardzie mastera byłby PUSTY. Health=alert, bo powstało
    # zadanie naprawcze - to samo w sobie jest sygnałem wymagającym uwagi.
    payload = {
        "events_scanned": 12,
        "repair_tasks_created": [{"kind": "job", "name": "runner_loop", "task_id": "KAC-001"}],
        "checked_at": "2026-08-22T10:00:00Z",
    }
    mapped = _map_status_payload(payload)
    assert mapped["health"] == "alert", "zadanie naprawcze powstało -> health musi być alert, nie ok"
    assert "1 zadań naprawczych" in mapped["message"]
    print("OK  kacper_monitor-kształt (z zadaniem naprawczym) -> health=alert + message, mimo braku 'details' w schemacie")


def test_map_status_payload_machine_status_synthesizes_readable_message():
    # Produkcyjny post_agent_status NIE ma pól tool_versions/ram_available_percent/
    # running_scripts — bez syntezy message ten wiersz byłby równie pusty jak kacper-monitor.
    payload = {
        "timestamp": "2026-08-22T12:00:00Z",
        "tool_versions": {"git": "2.44", "python": "3.11", "claude_code": None},
        "ram_available_percent": 55.0,
        "running_scripts": ["runner_loop.py"],
        "last_bootstrap": None,
    }
    mapped = _map_status_payload(payload)
    assert "git: 2.44" in mapped["message"]
    assert "RAM wolne: 55.0%" in mapped["message"]
    assert mapped["health"] == "ok", "machine_status_reporter nie niesie sygnału zdrowia -> domyślnie ok"
    print("OK  machine_status_reporter-kształt -> message z wersjami narzędzi + RAM, mimo braku 'details' w schemacie")


def test_real_live_status_publisher_payload_maps_cleanly():
    # Nie ręcznie sklejony fixture - PRAWDZIWY build_status() tego repo, żeby
    # test łapał drift, jeśli ktoś zmieni kształt payloadu w przyszłości.
    import live_status_publisher

    payload = live_status_publisher.build_status(role="dev")
    mapped = _map_status_payload(payload)
    assert mapped["details"] == payload
    assert mapped["health"] in ("ok", "alert")
    assert mapped["status"] == "idle", "build_status() nie ustawia 'status' w sensie working/idle/... -> fallback idle"
    print(f"OK  live_status_publisher.build_status() realny -> map_status_payload bez wyjątku (health={mapped['health']})")


def test_real_machine_status_payload_maps_cleanly():
    import machine_status_reporter

    payload = machine_status_reporter.build_machine_status()
    mapped = _map_status_payload(payload)
    assert mapped["details"] == payload
    assert mapped["health"] == "ok", "brak pola health/status w build_machine_status() -> domyślnie ok"
    assert mapped["status"] == "idle"
    assert mapped.get("message"), "wersje narzędzi (tool_versions) muszą trafić do message (produkcja nie ma 'details')"
    print(f"OK  machine_status_reporter.build_machine_status() realny -> map_status_payload bez wyjątku (message={mapped['message']!r})")


def test_real_system_health_payload_maps_cleanly():
    import system_health_monitor

    thresholds = system_health_monitor.load_thresholds()
    snapshot = system_health_monitor.get_system_snapshot()
    health = system_health_monitor.evaluate_health(snapshot, thresholds)
    payload = {**snapshot, "status": health["status"], "issues": health["issues"]}
    mapped = _map_status_payload(payload)
    assert mapped["details"] == payload
    assert mapped["health"] in ("ok", "alert")
    print(f"OK  system_health_monitor (status={health['status']}) realny -> map_status_payload bez wyjątku (health={mapped['health']})")


class _FakeMCPClient:
    def __init__(self):
        self.calls = []

    def call_tool(self, name, arguments=None):
        self.calls.append((name, arguments))
        return {}


def test_publish_status_calls_post_agent_status_when_transport_is_agent_status_tool():
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._cfg["live_status"] = {"transport": "agent_status_tool"}
    client._mcp = _FakeMCPClient()

    ok = client.publish_status("dev", {"current_task_id": "T-9", "health": "ok"})

    assert ok is True
    assert len(client._mcp.calls) == 1
    name, args = client._mcp.calls[0]
    assert name == "zbot_post_agent_status"
    assert args["roleLabel"] == "dev"
    assert args["currentTaskId"] == "T-9"
    print("OK  transport agent_status_tool -> woła MCP zbot_post_agent_status z roleLabel + polami kontraktu")


def test_publish_status_falls_back_to_documentation_by_default():
    client = ProjectlyClient(api_key="fake-token", base_url="http://fake.local/mcp")
    client._cfg["live_status"] = {"project": ""}  # brak projektu = tylko log, bez wywołania MCP
    client._mcp = _FakeMCPClient()

    ok = client.publish_status("dev", {"health": "ok"})

    assert ok is False, "brak live_status.project w trybie legacy -> tylko log, brak wywołania MCP"
    assert client._mcp.calls == [], "domyślny transport (documentation) nie może wołać zbot_post_agent_status"
    print("OK  domyślny transport (documentation, brak project) -> tylko log, zero wywołań MCP")


if __name__ == "__main__":
    test_map_status_payload_keeps_known_fields_and_full_details()
    test_map_status_payload_infers_alert_from_critical_health_status()
    test_map_status_payload_unknown_shape_still_preserved_in_details()
    test_map_status_payload_kacper_repairs_created_forces_alert_and_message()
    test_map_status_payload_machine_status_synthesizes_readable_message()
    test_real_live_status_publisher_payload_maps_cleanly()
    test_real_machine_status_payload_maps_cleanly()
    test_real_system_health_payload_maps_cleanly()
    test_publish_status_calls_post_agent_status_when_transport_is_agent_status_tool()
    test_publish_status_falls_back_to_documentation_by_default()
    print("\nWszystkie testy statusu na żywo przeszły.")
