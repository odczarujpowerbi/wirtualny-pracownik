"""
Test dymny google_workspace_client. Sprawdza logike bez sieci: from_env bez
sciezki -> None, konstruktor na nieistniejacym pliku -> GoogleAuthError, a na
istniejacym (atrapa) -> obiekt. Nie dotyka Google API.

Uzycie: python google_workspace_client_smoke_test.py
"""

import os
import sys
import tempfile
from pathlib import Path

import google_workspace_client as gw


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    saved = {k: os.environ.pop(k, None) for k in (gw.CREDENTIALS_ENV, gw.DELEGATED_USER_ENV)}
    try:
        checks.append(("from_env: brak sciezki -> None", gw.GoogleWorkspaceClient.from_env() is None))

        try:
            gw.GoogleWorkspaceClient("C:/nie/ma/klucza.json")
            raised = False
        except gw.GoogleAuthError:
            raised = True
        checks.append(("konstruktor: brak pliku -> GoogleAuthError", raised))

        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "sa.json"
            fake.write_text("{}", encoding="utf-8")
            os.environ[gw.CREDENTIALS_ENV] = str(fake)
            client = gw.GoogleWorkspaceClient.from_env()
            checks.append(("from_env: sciezka istnieje -> klient", client is not None))
            checks.append(("domyslny scope to drive.metadata.readonly",
                           gw.DEFAULT_SCOPES[0].endswith("drive.metadata.readonly")))
    finally:
        for k in (gw.CREDENTIALS_ENV, gw.DELEGATED_USER_ENV):
            os.environ.pop(k, None)
            if saved.get(k) is not None:
                os.environ[k] = saved[k]

    print("\n--- Wynik testu dymnego google_workspace_client ---")
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
