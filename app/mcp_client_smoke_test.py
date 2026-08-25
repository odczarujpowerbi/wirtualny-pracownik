"""
Test dymny MCPClient._parse_sse (żywy incydent 21.08.2026: serwer MCP wysłał
notyfikację progresu + finalny wynik jako dwa zdarzenia SSE; stara wersja
łączyła wszystkie linie 'data:' w jeden string przed json.loads(), co dawało
"Extra data" i wywalało runner_loop na każdym cyklu — patrz mcp_client.py)
oraz MCPClient._rpc — twardy CAŁKOWITY limit czasu (żywy incydent 25.08.2026:
"ciekące" połączenie event-stream zawiesiło runner_loop na 2+ godziny, mimo
że urlopen miał ustawiony `timeout` — ten parametr ogranicza tylko pojedynczy
odczyt/connect, nie cały czas wywołania).
"""

import time

import mcp_client
from mcp_client import MCPClient, MCPError


def test_single_sse_event_parses_as_before():
    text = 'data: {"jsonrpc": "2.0", "id": 1, "result": {"ok": true}}\n\n'
    parsed = MCPClient._parse_sse(text)
    assert parsed == {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    print("OK  jedno zdarzenie SSE parsuje sie jak dotad")


def test_progress_notification_then_final_result():
    text = (
        'data: {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"pct": 50}}\n\n'
        'data: {"jsonrpc": "2.0", "id": 7, "result": {"tasks": []}}\n\n'
    )
    parsed = MCPClient._parse_sse(text)
    assert parsed == {"jsonrpc": "2.0", "id": 7, "result": {"tasks": []}}, parsed
    print("OK  notyfikacja progresu + finalny wynik -> zwraca finalny wynik, nie 'Extra data'")


def test_error_response_is_returned():
    text = 'data: {"jsonrpc": "2.0", "id": 2, "error": {"code": -1, "message": "boom"}}\n\n'
    parsed = MCPClient._parse_sse(text)
    assert parsed == {"jsonrpc": "2.0", "id": 2, "error": {"code": -1, "message": "boom"}}
    print("OK  odpowiedz z 'error' rozpoznawana tak samo jak 'result'")


def test_no_final_response_returns_none():
    text = 'data: {"jsonrpc": "2.0", "method": "notifications/progress", "params": {"pct": 10}}\n\n'
    assert MCPClient._parse_sse(text) is None
    print("OK  sam progres bez finalnej odpowiedzi -> None (bez zgadywania)")


def test_rpc_enforces_total_timeout_on_leaking_connection():
    """Symuluje odpowiedź event-stream, która nigdy się nie kończy (serwer nie
    zamyka połączenia) — `urlopen` z jego per-operacyjnym `timeout` NIGDY by
    tego nie złapał. `_rpc` musi poddać się po całkowitym limicie i oddać
    kontrolę wywołującemu, nie wisieć w nieskończoność."""
    original_urlopen = mcp_client.urllib.request.urlopen
    original_grace = mcp_client._TOTAL_TIMEOUT_GRACE_SECONDS
    mcp_client._TOTAL_TIMEOUT_GRACE_SECONDS = 0.2  # test nie może czekać 15s+

    def _wiszący_urlopen(req, timeout=None):
        time.sleep(3600)  # nigdy realnie nie dobiegnie końca w czasie testu

    mcp_client.urllib.request.urlopen = _wiszący_urlopen
    try:
        client = MCPClient("http://fake.local/mcp", "token", timeout=0.1)
        start = time.monotonic()
        try:
            client._rpc("tools/call", {"name": "x"})
            raise AssertionError("_rpc powinno rzucić MCPError, nie zwrócić wyniku")
        except MCPError as exc:
            elapsed = time.monotonic() - start
            assert elapsed < 5, f"_rpc wisiało {elapsed:.1f}s — limit całkowity nie zadziałał"
            assert "nie odpowiedziało" in str(exc)
            print(f"OK  _rpc poddaje się po limicie całkowitym ({elapsed:.2f}s), nie wisi w nieskończoność")
    finally:
        mcp_client.urllib.request.urlopen = original_urlopen
        mcp_client._TOTAL_TIMEOUT_GRACE_SECONDS = original_grace


if __name__ == "__main__":
    test_single_sse_event_parses_as_before()
    test_progress_notification_then_final_result()
    test_error_response_is_returned()
    test_no_final_response_returns_none()
    test_rpc_enforces_total_timeout_on_leaking_connection()
    print("\nWszystkie testy MCPClient przeszły.")
