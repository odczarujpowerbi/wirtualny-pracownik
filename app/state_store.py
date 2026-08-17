"""
Trzyma stan zadań niezależnie od modelu AI, żeby dało się wznowić po restarcie
(PLAN-WDROZENIA.md sekcja 1, SKRYPTY.md kategoria A). Backend: SQLite, jeden plik,
zero zależności zewnętrznych.
"""

import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "runs" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    task_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payload TEXT NOT NULL,
    assigned_to TEXT,
    risk_level TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    detail TEXT,
    created_at TEXT NOT NULL
);
"""


def get_connection():
    """Publiczny dostęp do połączenia — do zapytań, których nie pokrywają
    gotowe funkcje pomocnicze poniżej (np. agregacje w cost_tracker.py)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    return conn


_connect = get_connection  # zachowana nazwa wewnętrzna dla zwięzłości w tym pliku


def upsert_task(task_id, payload, status="queued", assigned_to=None, risk_level=None, now=None):
    """Zapisuje/aktualizuje zadanie. `now` musi być podane przez wywołującego (ISO 8601)."""
    conn = _connect()
    with conn:
        conn.execute(
            """
            INSERT INTO tasks (task_id, status, payload, assigned_to, risk_level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                status=excluded.status,
                payload=excluded.payload,
                assigned_to=excluded.assigned_to,
                risk_level=excluded.risk_level,
                updated_at=excluded.updated_at
            """,
            (task_id, status, json.dumps(payload, ensure_ascii=False), assigned_to, risk_level, now),
        )
    conn.close()


def get_task(task_id):
    conn = _connect()
    row = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
    conn.close()
    if row is None:
        return None
    cols = ["task_id", "status", "payload", "assigned_to", "risk_level", "updated_at"]
    record = dict(zip(cols, row))
    record["payload"] = json.loads(record["payload"])
    return record


def list_tasks(status=None):
    conn = _connect()
    if status:
        rows = conn.execute("SELECT task_id, status FROM tasks WHERE status = ?", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT task_id, status FROM tasks").fetchall()
    conn.close()
    return [{"task_id": r[0], "status": r[1]} for r in rows]


def record_event(task_id, event_type, detail, now):
    """Dopisuje zdarzenie — tylko dopisywane, nigdy nadpisywane (jak events.jsonl w dokumentacji bazowej)."""
    conn = _connect()
    with conn:
        conn.execute(
            "INSERT INTO events (task_id, event_type, detail, created_at) VALUES (?, ?, ?, ?)",
            (task_id, event_type, detail, now),
        )
    conn.close()


def get_events(task_id):
    conn = _connect()
    rows = conn.execute(
        "SELECT event_type, detail, created_at FROM events WHERE task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    conn.close()
    return [{"event_type": r[0], "detail": r[1], "created_at": r[2]} for r in rows]
