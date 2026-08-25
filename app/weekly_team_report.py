"""
Raport tygodniowy z pracy CAŁEGO zespołu — zrobione/przeterminowane
zadania, zaległe wpisy czasu, wskazane słabe strony (PLAN-WDROZENIA.md
sekcje 10 i 16, SKRYPTY.md kategoria M). To nie jest nowa logika od zera:
łączy `digest_generator.split_tasks` (zadania) i
`stale_time_entry_nudger` (godziny) w jeden cykliczny raport zamiast
osobnych, mniejszych sygnałów — i dokłada warstwę interpretacji
("słabe strony", nie tylko liczby).

UCZCIWA GRANICA, ta sama co w digest_generator.py: "zrobione" = status w
Projectly, nie realna data wykonania w tym konkretnym tygodniu (pole
jeszcze nie istnieje, patrz PROJECTLY-ROZWOJ.md) — więc to bardziej "stan
na dziś" niż ścisłe "co zamknięto między poniedziałkiem a niedzielą".
Analiza godzin (jeśli podasz CSV) jest już naprawdę tygodniowa, bo eksport
ma konkretne daty.

Publikuje w Projectly (komentarz na stałym pseudo-zadaniu, jak
`ad_test_report.py`) i wysyła mailem — zgodnie z `config/email_safety.yaml`
dziś zawsze do człowieka wewnątrz firmy (Paweł), nie do całego zespołu.
"""

import os

import digest_generator
import model_registry
import stale_time_entry_nudger
from email_client import get_email_client
from projectly_client import get_client


def build_team_report(split, stale_grouped, invalid_dates=0, ai_summary=None):
    lines = ["📅 Raport tygodniowy zespołu", ""]

    lines.append(f"✅ Zrobione (stan na dziś, status w Projectly): {len(split['done'])}")
    for t in split["done"]:
        lines.append(f"   - {t['title']} ({t.get('assignee', '?')})")

    lines.append(f"\n🔴 Przeterminowane, nadal otwarte: {len(split['overdue'])}")
    for t in split["overdue"]:
        lines.append(f"   - {t['title']} ({t.get('assignee', '?')}) — termin był {t.get('dueDate')}")

    if stale_grouped:
        lines.append("\n⏰ Czas zalogowany jako 'otwarty' bez domknięcia (potencjalnie przepalony/niepoliczony):")
        for owner, data in sorted(stale_grouped.items(), key=lambda x: -x[1]["total_hours"]):
            lines.append(f"   - {owner}: {data['count']} wpisów, {data['total_hours']:.1f}h")
        if invalid_dates:
            lines.append(f"   - dodatkowo {invalid_dates} wpis(ów) z nieprawidłową datą (osobny problem jakości danych)")

    if ai_summary:
        lines.append("\n🧠 Obserwacje i słabe strony (ocena modelu na podstawie powyższych danych):")
        lines.append(ai_summary)
    else:
        lines.append(
            "\n(Brak ANTHROPIC_API_KEY — pominięto interpretację słabych stron, dostępne tylko surowe liczby powyżej.)"
        )

    return "\n".join(lines)


def ai_weaknesses_summary(split, stale_grouped):
    """Interpretacja wzorców ("dlaczego to jest problem", nie tylko "ile") —
    jedyna część tego raportu, która wymaga oceny, nie tylko zliczania
    (sekcja 12 planu: Python liczy, AI ocenia to, co niejednoznaczne).
    Fail-closed: bez klucza nie zmyślamy obserwacji."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None

    overdue_titles = [t["title"] for t in split["overdue"]]
    stale_summary = {owner: data["total_hours"] for owner, data in stale_grouped.items()}

    prompt = (
        "Na podstawie poniższych danych o zespole w tym tygodniu, wypisz 3-5 zwięzłych "
        "obserwacji o słabych stronach/wzorcach czasochłonności — konkretnie, bez lania wody:\n\n"
        f"Przeterminowane zadania: {overdue_titles}\n"
        f"Godziny zalogowane jako 'otwarte' bez domknięcia wg osoby: {stale_summary}\n"
    )
    client = anthropic.Anthropic()
    _, model = model_registry.resolve("weekly_team_report.generate")
    response = client.messages.create(model=model, max_tokens=400, messages=[{"role": "user", "content": prompt}])
    return response.content[0].text.strip()


def run_weekly_team_report(client=None, time_entries_csv=None, today=None, send_email_copy=True):
    client = client or get_client()
    tasks = client.list_tasks()
    split = digest_generator.split_tasks(tasks, today=today)

    stale_grouped, invalid_dates = {}, 0
    if time_entries_csv:
        entries = stale_time_entry_nudger.read_time_entries(time_entries_csv)
        stale, invalid = stale_time_entry_nudger.find_stale_entries(entries, today=today)
        grouped = stale_time_entry_nudger.group_by_owner(stale)
        stale_grouped = {k: {"count": v["count"], "total_hours": v["total_hours"]} for k, v in grouped.items()}
        invalid_dates = len(invalid)

    ai_summary = ai_weaknesses_summary(split, stale_grouped)
    text = build_team_report(split, stale_grouped, invalid_dates=invalid_dates, ai_summary=ai_summary)

    client.post_comment("WEEKLY-TEAM-REPORT", text)

    if send_email_copy:
        email_client = get_email_client()
        email_client.send_email(to="zespol@wewnetrzny", subject="Raport tygodniowy zespołu", body_text=text)

    return text


if __name__ == "__main__":
    from datetime import date

    from pathlib import Path

    demo_csv = Path(__file__).parent / "mock_data" / "sample_time_entries.csv"
    print(run_weekly_team_report(time_entries_csv=demo_csv, today=date(2026, 8, 17)))
