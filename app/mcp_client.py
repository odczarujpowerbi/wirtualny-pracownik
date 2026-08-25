"""
Transport MCP-over-HTTP (JSON-RPC) do serwera Projectly. To jest sama
"hydraulika" — nie wie nic o zadaniach, tylko jak rozmawiać z endpointem MCP
Streamable HTTP: initialize -> tools/call. Wiedza o TYM, które narzędzie MCP
do czego, siedzi w projectly_client.py i config/projectly.yaml.

Autoryzacja: token osobisty Bearer (prj_...) z PROJECTLY_API_KEY, endpoint z
PROJECTLY_BASE_URL (patrz .env.example, config/projectly.yaml). Bez tańca
OAuth — token statyczny wystarcza dla headless runnera.

Celowo stdlib (urllib), zero nowej zależności: to samo, czego użyto do
zweryfikowania kontraktu MCP na żywo w tej sesji.
"""

import json
import threading
import urllib.request

DEFAULT_PROTOCOL_VERSION = "2025-06-18"

# Ile DODATKOWO ponad `timeout` (per-operację gniazda) dajemy na CAŁE wywołanie,
# zanim uznajemy je za zawieszone i się poddajemy — żywy incydent 25.08.2026:
# `timeout` w urllib.request.urlopen ogranicza tylko POJEDYNCZY odczyt/connect,
# NIE całkowity czas wywołania. Odpowiedź text/event-stream, która "cieknie"
# (serwer wysyła np. jeden bajt/notyfikację progresu raz na 20s, nigdy nie
# zamykając połączenia) nigdy nie przekracza timeoutu per-operację, więc
# resp.read() czekał w praktyce W NIESKOŃCZONOŚĆ (2+ godziny, aż ktoś ręcznie
# zabił proces) — zamroziło to runner_loop/notebook_intake/kacper_monitor/
# system_health_monitor na godziny, bo wszystkie wołają publish_status.
_TOTAL_TIMEOUT_GRACE_SECONDS = 15


class MCPError(RuntimeError):
    """Błąd zwrócony przez serwer MCP albo transport (typed, nie string)."""


class MCPClient:
    """Minimalny klient MCP Streamable HTTP. Jedna instancja = jedna sesja;
    initialize odpala się leniwie przy pierwszym wywołaniu."""

    def __init__(self, base_url, token, client_name="wirtualny-pracownik", timeout=30):
        if not base_url or not token:
            raise MCPError("MCPClient wymaga base_url i token (PROJECTLY_BASE_URL / PROJECTLY_API_KEY).")
        self.base_url = base_url
        self._token = token
        self._client_name = client_name
        self._timeout = timeout
        self._session_id = None
        self._next_id = 1
        self._initialized = False

    def _blocking_request(self, req):
        """Sama sieciowa część _rpc — wywoływana w osobnym wątku daemon, żeby
        `_rpc` mogło wymusić TWARDY, CAŁKOWITY limit czasu (patrz _rpc), którego
        sam `timeout` w urlopen nie daje dla odpowiedzi typu event-stream."""
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            session = resp.headers.get("Mcp-Session-Id")
            content_type = resp.headers.get("Content-Type")
            raw = resp.read()
        return session, raw, content_type

    def _rpc(self, method, params=None, is_notification=False):
        body = {"jsonrpc": "2.0", "method": method}
        if not is_notification:
            body["id"] = self._next_id
            self._next_id += 1
        if params is not None:
            body["params"] = params

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id

        req = urllib.request.Request(
            self.base_url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
        )

        wynik = {}

        def _worker():
            try:
                wynik["ok"] = self._blocking_request(req)
            except BaseException as exc:  # noqa: BLE001 — przekazujemy przez wynik, nie przez wyjątek w wątku
                wynik["exc"] = exc

        wątek = threading.Thread(target=_worker, daemon=True)
        wątek.start()
        limit_calkowity = self._timeout + _TOTAL_TIMEOUT_GRACE_SECONDS
        wątek.join(timeout=limit_calkowity)
        if wątek.is_alive():
            # Wątek zostaje osierocony (daemon=True — nie blokuje zamknięcia
            # procesu), ale WYWOŁUJĄCY dostaje kontrolę z powrotem od razu,
            # zamiast czekać bez końca na "ciekące" połączenie.
            raise MCPError(
                f"MCP '{method}' nie odpowiedziało w {limit_calkowity}s (limit całkowity) — "
                "połączenie mogło 'ciec' (event-stream bez końca) mimo timeoutu per-operację."
            )

        try:
            session, raw, content_type = wynik["ok"]
        except KeyError:
            exc = wynik["exc"]
            if isinstance(exc, urllib.error.HTTPError):
                detail = exc.read().decode("utf-8", "replace")[:500]
                raise MCPError(f"HTTP {exc.code} na '{method}': {detail}") from exc
            if isinstance(exc, urllib.error.URLError):
                raise MCPError(f"Błąd sieci na '{method}': {exc.reason}") from exc
            raise

        if session:
            self._session_id = session
        parsed = self._parse_body(raw, content_type)

        if is_notification:
            return None
        if parsed and "error" in parsed:
            raise MCPError(f"MCP '{method}' zwróciło błąd: {parsed['error']}")
        return parsed

    @staticmethod
    def _parse_body(raw, content_type):
        text = raw.decode("utf-8", "replace")
        if "text/event-stream" in (content_type or ""):
            return MCPClient._parse_sse(text)
        if not text.strip():
            return None
        return json.loads(text)

    @staticmethod
    def _parse_sse(text):
        """SSE (text/event-stream): każda linia 'data:' to WŁASNY, kompletny
        komunikat JSON-RPC (odpowiedź albo notyfikacja progresu) — NIE fragment
        jednego JSON-a rozbitego na wiele linii. Poprzednia wersja łączyła
        wszystkie linie 'data:' w jeden string przed json.loads(): gdy serwer
        wysłał więcej niż jedno zdarzenie dla tego samego wywołania (np.
        notyfikację progresu + finalny wynik), dawało to dwa poprawne dokumenty
        JSON zlepione w jeden string i błąd "Extra data" (żywy incydent
        21.08.2026 — runner_loop padał na każdym cyklu z tego powodu). Zwracamy
        ostatnią wiadomość z 'result' albo 'error' (finalna odpowiedź JSON-RPC);
        notyfikacje bez tych pól po drodze pomijamy."""
        last_response = None
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if not payload:
                continue
            try:
                parsed = json.loads(payload)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and ("result" in parsed or "error" in parsed):
                last_response = parsed
        return last_response

    def _ensure_initialized(self):
        if self._initialized:
            return
        self._rpc(
            "initialize",
            {
                "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": "0.1"},
            },
        )
        # Powiadomienie initialized (bez id) — część protokołu MCP.
        self._rpc("notifications/initialized", {}, is_notification=True)
        self._initialized = True

    def call_tool(self, name, arguments=None):
        """Wywołuje narzędzie MCP i zwraca zdekodowaną treść. Serwer Projectly
        pakuje wynik jako pojedynczy blok text z JSON-em w środku — rozpakowujemy
        go tutaj, żeby projectly_client dostawał gotowy dict/list."""
        self._ensure_initialized()
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        content = (result or {}).get("result", {}).get("content", [])
        for block in content:
            if block.get("type") == "text":
                text = block.get("text", "")
                try:
                    return json.loads(text)
                except (ValueError, TypeError):
                    return text
        return result
