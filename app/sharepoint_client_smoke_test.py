"""
Test dymny konektora SharePoint (Microsoft Graph). Nie wymaga msal, requests
ani sieci — token i warstwa HTTP są podmieniane na atrapy, więc test sprawdza
LOGIKĘ (rozwiązanie witryny/drive'a, budowa ścieżek children, obsługa 409 jako
sukces, kody błędów -> SharePointWriteError), nie prawdziwy zapis.

Użycie:
    python sharepoint_client_smoke_test.py
"""

import sys

import sharepoint_client as sp


class _FakeResponse:
    def __init__(self, status_code, body=None, text=None):
        self.status_code = status_code
        self._body = body or {}
        self.text = text if text is not None else str(body)

    def json(self):
        return self._body


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    calls = []

    client = sp.SharePointClient("cid", "secret", "tenant", "contoso.sharepoint.com", "/sites/Team")
    client._acquire_token = lambda: "FAKE_TOKEN"

    responses = {}

    def fake_request(method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return responses[len(calls) - 1]

    client._request = fake_request

    # 1. resolve_drive: site GET -> drive GET -> cache w instancji.
    responses[0] = _FakeResponse(200, {"id": "site123"})
    responses[1] = _FakeResponse(200, {"id": "drive456", "webUrl": "https://contoso.sharepoint.com/sites/Team/Shared%20Documents"})
    drive_id = client.resolve_drive()
    checks.append(("resolve_drive: zwraca id drive'a", drive_id == "drive456"))
    checks.append(("resolve_drive: URL witryny zawiera host:path",
                   calls[0]["url"] == "https://graph.microsoft.com/v1.0/sites/contoso.sharepoint.com:/sites/Team"))
    checks.append(("resolve_drive: cache — druga wołanie nie robi nowych requestów",
                   client.resolve_drive() == "drive456" and len(calls) == 2))

    # 2. ensure_folder: 201 -> tworzy, poprawny URL children (root i zagnieżdżony).
    calls.clear()
    responses.clear()
    responses[0] = _FakeResponse(201, {"id": "f1"})
    responses[1] = _FakeResponse(201, {"id": "f2"})
    client.ensure_folder("Zadania-Agenta/2026-08-22_test")
    checks.append(("ensure_folder: pierwszy segment na root/children",
                   calls[0]["url"].endswith("/drives/drive456/root/children")))
    checks.append(("ensure_folder: drugi segment zagnieżdżony po ścieżce",
                   calls[1]["url"].endswith("/drives/drive456/root:/Zadania-Agenta:/children")))
    checks.append(("ensure_folder: conflictBehavior=fail w payloadzie",
                   calls[0]["json"]["@microsoft.graph.conflictBehavior"] == "fail"))

    # 3. ensure_folder: 409 (już istnieje) traktowane jako sukces, nie wyjątek.
    calls.clear()
    responses.clear()
    responses[0] = _FakeResponse(409, text="already exists")
    try:
        client.ensure_folder("Zadania-Agenta")
        no_raise = True
    except sp.SharePointWriteError:
        no_raise = False
    checks.append(("ensure_folder: 409 nie podnosi wyjątku (idempotentne)", no_raise))

    # 4. ensure_folder: inny kod błędu -> SharePointWriteError.
    calls.clear()
    responses.clear()
    responses[0] = _FakeResponse(500, text="boom")
    try:
        client.ensure_folder("Zadania-Agenta")
        raised = False
    except sp.SharePointWriteError:
        raised = True
    checks.append(("ensure_folder: 500 -> SharePointWriteError", raised))

    # 5. upload_file: PUT z Content-Type octet-stream, 201 -> zwraca json odpowiedzi.
    calls.clear()
    responses.clear()
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "demo.txt"
        local.write_text("tresc testowa", encoding="utf-8")
        responses[0] = _FakeResponse(201, {"id": "item789"})
        result = client.upload_file(local, "Zadania-Agenta/demo.txt")
    checks.append(("upload_file: zwraca id nowego elementu", result["id"] == "item789"))
    checks.append(("upload_file: URL PUT .../content",
                   calls[0]["url"].endswith("/drives/drive456/root:/Zadania-Agenta/demo.txt:/content")))
    checks.append(("upload_file: metoda PUT", calls[0]["method"] == "PUT"))

    # 6. resolve_drive z biblioteką po nazwie (drives -> match po 'name').
    client2 = sp.SharePointClient("cid", "secret", "tenant", "contoso.sharepoint.com", "/sites/Team", library="Inna Biblioteka")
    client2._acquire_token = lambda: "FAKE_TOKEN"
    calls2 = []
    responses2 = {}

    def fake_request2(method, url, **kwargs):
        calls2.append({"method": method, "url": url, **kwargs})
        return responses2[len(calls2) - 1]

    client2._request = fake_request2
    responses2[0] = _FakeResponse(200, {"id": "siteXYZ"})
    responses2[1] = _FakeResponse(200, {"value": [
        {"id": "d1", "name": "Documents", "webUrl": "..."},
        {"id": "d2", "name": "Inna Biblioteka", "webUrl": "https://x/inna"},
    ]})
    drive_id2 = client2.resolve_drive()
    checks.append(("resolve_drive: wybiera drive po nazwie biblioteki", drive_id2 == "d2"))

    # 7. get_sharepoint_client: brak sekretów -> None (fail-closed, nie crash).
    import os
    for k in ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET", "MS_GRAPH_TENANT_ID"):
        os.environ.pop(k, None)
    checks.append(("get_sharepoint_client: brak sekretów -> None", sp.get_sharepoint_client() is None))

    print("\n--- Wynik testu dymnego konektora SharePoint ---")
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
