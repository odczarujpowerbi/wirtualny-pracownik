"""
Cykliczny digest aktywności z Projectly, do puszczenia PRZED daily/weekly,
żeby skrócić albo częściowo zastąpić spotkanie zamiast tylko podsumowywać
je po fakcie (PLAN-WDROZENIA.md sekcja 10, SKRYPTY.md kategoria M).
Bezpośrednia odpowiedź na największe pojedyncze znalezisko z analizy
raportu godzin: koordynacja/spotkania to 392,8h w 438 wpisach — ok. 20%
wszystkich godzin zespołu (sekcja 10 planu).

UCZCIWA GRANICA: Projectly nie ma dziś pola z realną datą wykonania
(PROJECTLY-ROZWOJ.md, potwierdzone przez MCP) — ten digest pokazuje więc
"zrobione = status done" i "przeterminowane = otwarte + dueDate w
przeszłości", nie "zrobione w tym konkretnym okresie". Dokładniejszy
digest (naprawdę "co zrobiono w ostatnim tygodniu") wymaga pola
completedAt z tamtego dokumentu.
"""

from datetime import date, datetime, timezone

from projectly_client import get_client

DONE_STATUSES = {"done"}
OPEN_STATUSES = {"todo", "in_progress"}


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def split_tasks(tasks, today=None):
    """Dzieli zadania na zrobione / otwarte-w-terminie / przeterminowane.
    `today` przyjmowane jako argument (nie liczone w środku), żeby dało się
    testować deterministycznie bez zależności od zegara systemowego."""
    today = today or date.today()

    done, open_on_time, overdue = [], [], []
    for t in tasks:
        status = t.get("status")
        due = _parse_date(t.get("dueDate"))

        if status in DONE_STATUSES:
            done.append(t)
        elif status in OPEN_STATUSES:
            if due and due < today:
                overdue.append(t)
            else:
                open_on_time.append(t)
    return {"done": done, "open_on_time": open_on_time, "overdue": overdue}


def build_digest(split, project_label="wszystkie projekty"):
    lines = [f"🗒️ Digest aktywności — {project_label}", ""]

    lines.append(f"✅ Zrobione ({len(split['done'])}):")
    if split["done"]:
        for t in split["done"]:
            lines.append(f"   - {t['title']} ({t.get('assignee', '?')})")
    else:
        lines.append("   - brak")

    lines.append(f"\n🔴 Przeterminowane, nadal otwarte ({len(split['overdue'])}):")
    if split["overdue"]:
        for t in split["overdue"]:
            lines.append(f"   - {t['title']} ({t.get('assignee', '?')}) — termin był {t.get('dueDate')}")
    else:
        lines.append("   - brak")

    lines.append(f"\n🟡 W toku, w terminie ({len(split['open_on_time'])}):")
    if split["open_on_time"]:
        for t in split["open_on_time"]:
            lines.append(f"   - {t['title']} ({t.get('assignee', '?')}) — termin {t.get('dueDate', 'brak')}")
    else:
        lines.append("   - brak")

    lines.append(
        "\n⚠️ Uwaga: 'zrobione' = status w Projectly, nie realna data wykonania "
        "(pole jeszcze nie istnieje — patrz PROJECTLY-ROZWOJ.md)."
    )
    return "\n".join(lines)


def generate_digest(client=None, project_id=None, project_label=None, today=None):
    client = client or get_client()
    tasks = client.list_tasks(project_id=project_id)
    split = split_tasks(tasks, today=today)
    text = build_digest(split, project_label=project_label or (project_id or "wszystkie projekty"))

    digest_task_id = f"DIGEST-{(project_id or 'ALL').upper()}"
    client.post_comment(digest_task_id, text)
    return text


if __name__ == "__main__":
    print(generate_digest(today=date(2026, 8, 17)))
