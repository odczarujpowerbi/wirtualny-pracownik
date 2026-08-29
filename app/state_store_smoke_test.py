"""
Test dymny state_store.py — potwierdza, że get_connection() ustawia tryb WAL
(dodane 29.08.2026, bo od tej daty kilka procesów bota — dev/checker/
marketing, patrz BOT_ROLE — może pisać do TEGO SAMEGO runs/state.db
równocześnie) i że dwa niezależne połączenia do tej samej bazy naprawdę
widzą swoje zapisy nawzajem (nie tylko "nie wywala się").

Używa TYMCZASOWEJ bazy — zero wpływu na prawdziwe runs/state.db.

Użycie:
    python state_store_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import state_store


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_db_path = state_store.DB_PATH

    try:
        state_store.DB_PATH = Path(tempfile.mkdtemp()) / "state.db"

        conn = state_store.get_connection()
        tryb = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        checks.append(("get_connection() ustawia tryb WAL (współbieżny dostęp)",
                       tryb.lower() == "wal"))

        # Dwa NIEZALEŻNE połączenia (symulacja dwóch procesów pod różnymi
        # rolami) — zapis jednym, odczyt drugim, bez zamykania pierwszego.
        conn_a = state_store.get_connection()
        conn_b = state_store.get_connection()
        now = "2026-08-29T00:00:00+00:00"
        state_store.upsert_task("T-WAL", payload={"title": "Test WAL"}, status="todo", now=now)
        widziane_przez_b = conn_b.execute(
            "SELECT status FROM tasks WHERE task_id = ?", ("T-WAL",)
        ).fetchone()
        conn_a.close()
        conn_b.close()
        checks.append(("Zapis jednym połączeniem widoczny w drugim (współbieżny dostęp działa)",
                       widziane_przez_b is not None and widziane_przez_b[0] == "todo"))

        # get_task/upsert_task/record_event (ścieżka używana wszędzie) nadal
        # działają normalnie po zmianie trybu dziennika — brak regresji.
        state_store.record_event("T-WAL", "test_event", "szczegół", now)
        zadanie = state_store.get_task("T-WAL")
        zdarzenia = state_store.get_events("T-WAL")
        checks.append(("get_task/get_events nadal działają poprawnie z trybem WAL",
                       zadanie is not None and zadanie["status"] == "todo"
                       and any(e["event_type"] == "test_event" for e in zdarzenia)))
    finally:
        state_store.DB_PATH = original_db_path

    print("\n--- Wynik testu dymnego state_store ---")
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
