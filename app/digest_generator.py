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

import json
from datetime import date, datetime, timezone
from pathlib import Path

from projectly_client import get_client

DONE_STATUSES = {"done"}
OPEN_STATUSES = {"todo", "in_progress"}

# Mapowanie project_id ("ALL" dla wszystkich projektów naraz) -> id REALNEGO
# zadania w Projectly, na którym digest jest publikowany jako komentarz.
# Zadanie jest tworzone RAZ (patrz _digest_task_id) i zapamiętywane tu trwale.
DIGEST_TASK_IDS_PATH = Path(__file__).parent / "runs" / "digest_task_ids.json"

# Adres biblioteki dokumentów agenta na SharePoint — ten sam, co w
# config/sharepoint.yaml (site_host + site_path + library). Trzymany jako
# osobna stała, żeby zmiana witryny/biblioteki była jedną podmianą, a nie
# przepisywaniem każdego wpisu w mapowaniu niżej.
SHAREPOINT_LIBRARY_URL = "https://odczarujlowcode.sharepoint.com/sites/Wirtualny-pracownik/Dokumenty"

# Zadanie/kategoria -> folder SharePoint z materiałami, pokazywany przy pozycji
# w sekcji "Zrobione".
#
# Klucz działa dwustopniowo (patrz sharepoint_folder_url):
#   - dokładny `task_id` albo dokładny `title` — dopasowanie konkretnego zadania,
#     ma pierwszeństwo,
#   - słowo kluczowe kategorii (klient/obszar) szukane W TYTULE, bez względu na
#     wielkość liter — te same słowa co w config/clients_routing.yaml, żeby dwa
#     słowniki się nie rozjeżdżały.
#
# Zadanie bez dopasowania renderuje się BEZ linku — to normalna sytuacja, nie błąd.
#
# UCZCIWA GRANICA: zweryfikowana jest tylko część adresu do biblioteki włącznie
# (SHAREPOINT_LIBRARY_URL, wprost z config/sharepoint.yaml) oraz folder
# `Zadania-Agenta` (root_folder z tego samego pliku). Nazwy podfolderów klientów
# poniżej to PROPOZYCJA wg struktury z reguł Power BI, NIE potwierdzony stan
# biblioteki — przed pierwszym cyklem podmień je na adresy skopiowane z
# przeglądarki (przycisk "Kopiuj link" w SharePoint) albo usuń wpis: zadanie bez
# wpisu po prostu nie dostanie linku.
SHAREPOINT_FOLDER_LINKS = {
    "indeka": f"{SHAREPOINT_LIBRARY_URL}/Klienci/INDEKA",
    "diverse": f"{SHAREPOINT_LIBRARY_URL}/Klienci/Diverse",
    "magnapharm": f"{SHAREPOINT_LIBRARY_URL}/Klienci/Magnapharm",
    "kajzerka": f"{SHAREPOINT_LIBRARY_URL}/Klienci/Kajzerka",
    "kalkulator": f"{SHAREPOINT_LIBRARY_URL}/Okolosprzedazowe/Kalkulator",
    # Archiwum wyników zadań agenta (config/sharepoint.yaml -> root_folder),
    # jeden podfolder per zadanie zakładany przez runner_loop._save_result_to_onedrive.
    "zadania agenta": f"{SHAREPOINT_LIBRARY_URL}/Zadania-Agenta",
}


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def sharepoint_folder_url(task, links=None):
    """URL folderu SharePoint dla zadania albo None, gdy nic nie pasuje.

    Kolejność: dokładny `task_id` -> dokładny `title` -> słowo kluczowe kategorii
    zawarte w tytule. Brak dopasowania to poprawny wynik (None), nie wyjątek —
    większość zadań nie ma dedykowanego folderu."""
    links = SHAREPOINT_FOLDER_LINKS if links is None else links

    for exact_key in (task.get("task_id"), task.get("title")):
        if exact_key in links:
            return links[exact_key]

    title = (task.get("title") or "").lower()
    if not title:
        return None
    for keyword, url in links.items():
        if keyword.lower() in title:
            return url
    return None


def format_done_task(task, links=None):
    """Jedna pozycja sekcji 'Zrobione', z klikalnym linkiem Markdown do folderu
    SharePoint, jeśli zadanie jest objęte mapowaniem."""
    line = f"   - {task['title']} ({task.get('assignee', '?')})"
    url = sharepoint_folder_url(task, links=links)
    if url:
        line += f" — [📁 materiały na SharePoint]({url})"
    return line


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
            lines.append(format_done_task(t))
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


def _wczytaj_id_zadan_digestu(path=None):
    # path=None -> DIGEST_TASK_IDS_PATH odczytane TERAZ, nie przy definicji
    # funkcji — wartość domyślna parametru wiąże się RAZ, przy imporcie modułu,
    # więc podmiana digest_generator.DIGEST_TASK_IDS_PATH w teście (ten sam
    # wzorzec co state_store.DB_PATH) inaczej by nie zadziałała.
    path = path or DIGEST_TASK_IDS_PATH
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _zapisz_id_zadan_digestu(mapowanie, path=None):
    path = path or DIGEST_TASK_IDS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(mapowanie, ensure_ascii=False, indent=2), encoding="utf-8")


def _digest_task_id(client, project_id, path=None):
    """ID REALNEGO zadania w Projectly, na którym publikowany jest digest dla
    danego project_id ("ALL" = wszystkie projekty naraz) — tworzone RAZ, potem
    tylko aktualizowane komentarzem. Bez tego post_comment() celował w
    zmyślony, nigdy nie istniejący task_id (żywy bug 26.08.2026, znaleziony w
    audycie 27.08.2026: digest nigdy realnie nie docierał do człowieka, mimo
    że job_scheduler zawsze raportował status=ok).

    Fail-soft: brak project_id I brak default_admin_project -> None (digest
    zostaje tylko zwróconą wartością/logiem, nie próbujemy zgadywać projektu)."""
    klucz = project_id or "ALL"
    mapowanie = _wczytaj_id_zadan_digestu(path)
    if klucz in mapowanie:
        return mapowanie[klucz]

    docelowy_projekt = project_id or client.default_admin_project_id()
    if not docelowy_projekt:
        print(f"[digest_generator] Brak project_id i default_admin_project dla '{klucz}' "
              "— NIE tworzę zadania-kanału w Projectly.")
        return None

    nowy_id = client.create_task(
        f"Digest aktywności — {klucz}",
        "Cykliczny digest aktywności (digest_generator.py) — aktualizowany komentarzami, "
        "nie zadanie do wykonania.",
        assigned_to="unassigned_pool", project_id=docelowy_projekt,
    )
    mapowanie[klucz] = nowy_id
    _zapisz_id_zadan_digestu(mapowanie, path)
    return nowy_id


def generate_digest(client=None, project_id=None, project_label=None, today=None):
    client = client or get_client()
    tasks = client.list_tasks(project_id=project_id)
    split = split_tasks(tasks, today=today)
    text = build_digest(split, project_label=project_label or (project_id or "wszystkie projekty"))

    digest_task_id = _digest_task_id(client, project_id)
    if digest_task_id:
        client.post_comment(digest_task_id, text)
    return text


if __name__ == "__main__":
    print(generate_digest(today=date(2026, 8, 17)))
