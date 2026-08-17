"""
Skanuje eksport CSV wpisów czasu (te same kolumny co eksport z Projectly:
Tytuł, Opis, Twórca, Data, Start, Koniec, Godziny, Projekt, Deadline,
Status) i znajduje wpisy utknięte w statusie "otwarte" dłużej niż ustalony
próg dni — PLAN-WDROZENIA.md sekcja 10, SKRYPTY.md kategoria M.

Bezpośrednia odpowiedź na konkretne znalezisko z analizy realnego raportu
godzin: 298h zalogowane jako wciąż "otwarte" (265,6h u jednej osoby), część
prawdopodobnie od tygodni bez zamknięcia. To nie koszt pracy tylko luka w
śledzeniu — potwierdza z innej strony problem opisany w PROJECTLY-ROZWOJ.md
(brak realnej daty wykonania, nic nie wymusza domknięcia wpisu).

UCZCIWA GRANICA: dziś nie ma potwierdzonego API do wpisów czasu w Projectly
(tylko do zadań, patrz projectly_client.py) — ten skrypt działa więc na
eksporcie CSV, dokładnie takim, jaki już dziś da się wyciągnąć ręcznie.
Da się uruchomić OD RAZU na prawdziwym pliku:
    python stale_time_entry_nudger.py sciezka/do/eksportu.csv
"""

import csv
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from projectly_client import get_client


def _parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _hours(row):
    try:
        return float(str(row.get("Godziny", "0")).replace(",", "."))
    except ValueError:
        return 0.0


def read_time_entries(csv_path):
    with open(csv_path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def find_stale_entries(entries, today=None, threshold_days=5):
    """Zwraca (stale, invalid_date) — invalid_date to osobny problem jakości
    danych (data 1970-01-01/pusta), nie licz go jako 'tysiące dni otwarte'."""
    today = today or date.today()
    stale, invalid_date = [], []

    for row in entries:
        if row.get("Status") != "otwarte":
            continue
        d = _parse_date(row.get("Data"))
        if d is None or d.year < 2000:
            invalid_date.append(row)
            continue
        days_open = (today - d).days
        if days_open >= threshold_days:
            row = dict(row)
            row["_days_open"] = days_open
            stale.append(row)

    return stale, invalid_date


def group_by_owner(stale_entries):
    grouped = defaultdict(lambda: {"count": 0, "total_hours": 0.0, "entries": []})
    for row in stale_entries:
        g = grouped[row.get("Twórca", "?")]
        g["count"] += 1
        g["total_hours"] += _hours(row)
        g["entries"].append(row)
    return grouped


def build_nudge_report(grouped, invalid_date_count=0, threshold_days=5):
    lines = [f"⏰ Wpisy czasu 'otwarte' dłużej niż {threshold_days} dni", ""]

    if not grouped:
        lines.append("Brak — wszystko domknięte na czas. ✅")
    else:
        for owner, data in sorted(grouped.items(), key=lambda x: -x[1]["total_hours"]):
            lines.append(f"### {owner} — {data['count']} wpisów, {data['total_hours']:.1f}h wciąż otwartych")
            for e in sorted(data["entries"], key=lambda r: -r["_days_open"])[:10]:
                lines.append(
                    f"   - {e.get('Tytuł') or '(bez tytułu)'} — otwarte od {e['_days_open']} dni, "
                    f"{_hours(e):.2f}h ({e.get('Projekt', '?')})"
                )
            lines.append("")

    if invalid_date_count:
        lines.append(
            f"⚠️ Dodatkowo {invalid_date_count} wpis(ów) ma nieprawidłową/pustą datę "
            "— osobny problem jakości danych, nie policzony wyżej jako 'dni otwarte'."
        )

    return "\n".join(lines)


def run_nudge(csv_path, client=None, today=None, threshold_days=5, create_tasks=False):
    entries = read_time_entries(csv_path)
    stale, invalid_date = find_stale_entries(entries, today=today, threshold_days=threshold_days)
    grouped = group_by_owner(stale)
    report = build_nudge_report(grouped, invalid_date_count=len(invalid_date), threshold_days=threshold_days)

    created_tasks = []
    if create_tasks and grouped:
        client = client or get_client()
        for owner, data in grouped.items():
            sample_titles = "; ".join((e.get("Tytuł") or "(bez tytułu)") for e in data["entries"][:5])
            task_id = client.create_task(
                title=f"Domknij zaległe wpisy czasu ({data['count']})",
                description=(
                    f"{data['count']} wpisów czasu wciąż 'otwarte', łącznie {data['total_hours']:.1f}h. "
                    f"Najstarsze: {sample_titles}."
                ),
                assigned_to=owner,
            )
            created_tasks.append({"owner": owner, "task_id": task_id})

    return {
        "report": report,
        "grouped": {k: {"count": v["count"], "total_hours": round(v["total_hours"], 1)} for k, v in grouped.items()},
        "invalid_dates": len(invalid_date),
        "created_tasks": created_tasks,
    }


if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "mock_data" / "sample_time_entries.csv"
    result = run_nudge(path, today=date(2026, 8, 17))
    print(result["report"])
