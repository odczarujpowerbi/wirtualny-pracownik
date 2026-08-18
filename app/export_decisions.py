"""
Eksport historii decyzji agentów (M2b) z lokalnej bazy `runs/state.db` do pliku
CSV albo JSONL — żeby właściciel mógł analizować przepływy offline i na tej
podstawie dopracowywać skille. Nic nie kasuje: to czysty odczyt bazy, która i
tak jest append-only. Historia zostaje w bazie, eksport to jej migawka.

Użycie:
    python export_decisions.py                       # wszystkie decyzje -> runs/decisions_export.jsonl
    python export_decisions.py --format csv          # -> runs/decisions_export.csv
    python export_decisions.py --since 2026-08-01    # tylko od daty (created_at >= )
    python export_decisions.py --out C:/tmp/dec.csv --format csv
"""

import argparse
import csv
import json
from pathlib import Path

import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)
import state_store

FIELDS = ["id", "task_id", "event_type", "created_at", "agent",
          "decision", "reason", "model", "cost_usd", "duration_ms"]
DEFAULT_DIR = Path(__file__).parent / "runs"


def fetch_decisions(since=None):
    """Wszystkie decyzje (agent IS NOT NULL), najstarsze pierwsze — naturalna
    kolejność do analizy przebiegu. `since` (ISO) filtruje created_at >= since."""
    conn = state_store.get_connection()
    query = f"SELECT {', '.join(FIELDS)} FROM events WHERE agent IS NOT NULL"
    params = []
    if since:
        query += " AND created_at >= ?"
        params.append(since)
    query += " ORDER BY id ASC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(zip(FIELDS, row)) for row in rows]


def write_jsonl(decisions, out_path):
    with open(out_path, "w", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")


def write_csv(decisions, out_path):
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(decisions)


def export(since=None, fmt="jsonl", out=None):
    decisions = fetch_decisions(since=since)
    out_path = Path(out) if out else DEFAULT_DIR / f"decisions_export.{fmt}"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    (write_csv if fmt == "csv" else write_jsonl)(decisions, out_path)
    return {"count": len(decisions), "path": str(out_path)}


def main():
    parser = argparse.ArgumentParser(description="Eksport decyzji agentów z state.db.")
    parser.add_argument("--since", help="Tylko decyzje od tej daty ISO (created_at >=), np. 2026-08-01")
    parser.add_argument("--format", choices=["jsonl", "csv"], default="jsonl")
    parser.add_argument("--out", help="Ścieżka pliku wyjściowego (domyślnie runs/decisions_export.<format>)")
    args = parser.parse_args()

    result = export(since=args.since, fmt=args.format, out=args.out)
    print(f"Wyeksportowano {result['count']} decyzji do {result['path']}")


if __name__ == "__main__":
    main()
