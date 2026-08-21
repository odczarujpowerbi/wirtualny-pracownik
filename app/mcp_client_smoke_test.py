"""
Test dymny MCPClient._parse_sse (żywy incydent 21.08.2026: serwer MCP wysłał
notyfikację progresu + finalny wynik jako dwa zdarzenia SSE; stara wersja
łączyła wszystkie linie 'data:' w jeden string przed json.loads(), co dawało
"Extra data" i wywalało runner_loop na każdym cyklu — patrz mcp_client.py).
"""

from mcp_client import MCPClient


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


if __name__ == "__main__":
    test_single_sse_event_parses_as_before()
    test_progress_notification_then_final_result()
    test_error_response_is_returned()
    test_no_final_response_returns_none()
    print("\nWszystkie testy MCPClient przeszły.")
