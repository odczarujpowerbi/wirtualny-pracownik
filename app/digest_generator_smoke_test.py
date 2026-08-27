"""
Test dymny mapowania folderów SharePoint w digeście aktywności
(digest_generator.SHAREPOINT_FOLDER_LINKS): zadanie objęte mapowaniem dostaje
klikalny link Markdown przy pozycji w sekcji "Zrobione", zadanie bez dopasowania
renderuje się bez linku i BEZ błędu.

Bez sieci i bez Projectly — testowane są czyste funkcje renderujące
(sharepoint_folder_url / format_done_task / build_digest), nie klient MCP.
"""

import tempfile
from datetime import date
from pathlib import Path

import digest_generator
from digest_generator import build_digest, format_done_task, sharepoint_folder_url, split_tasks

# Własne mapowanie testowe zamiast produkcyjnego — test sprawdza MECHANIZM
# dopasowania, a nie to, jakie adresy akurat są dziś wpisane w stałej.
LINKS = {
    "PRJ-0001": "https://example.sharepoint.com/sites/W/Dokumenty/Zadania/PRJ-0001",
    "Waliduj strukturę PBIP raportu Sales": "https://example.sharepoint.com/sites/W/Dokumenty/PBIP/Sales",
    "magnapharm": "https://example.sharepoint.com/sites/W/Dokumenty/Klienci/Magnapharm",
}


def test_exact_task_id_wins_over_keyword():
    task = {"task_id": "PRJ-0001", "title": "Magnapharm: commit poprawki"}
    assert sharepoint_folder_url(task, links=LINKS) == LINKS["PRJ-0001"], \
        "dopasowanie po task_id musi mieć pierwszeństwo nad słowem kluczowym w tytule"
    print("OK  dokładny task_id ma pierwszeństwo nad kategorią")


def test_exact_title_match():
    task = {"task_id": "PRJ-0005", "title": "Waliduj strukturę PBIP raportu Sales"}
    assert sharepoint_folder_url(task, links=LINKS) == LINKS["Waliduj strukturę PBIP raportu Sales"]
    print("OK  dokładny tytuł zadania dopasowany do folderu")


def test_category_keyword_is_case_insensitive():
    task = {"task_id": "PRJ-0002", "title": "MAGNAPHARM: commit poprawki na gałęzi"}
    assert sharepoint_folder_url(task, links=LINKS) == LINKS["magnapharm"], \
        "kategoria musi łapać niezależnie od wielkości liter"
    print("OK  kategoria dopasowana po fragmencie tytułu, bez względu na wielkość liter")


def test_no_match_returns_none_without_error():
    assert sharepoint_folder_url({"task_id": "PRJ-0003", "title": "Zwiększ budżet kampanii Meta Ads"}, links=LINKS) is None
    assert sharepoint_folder_url({}, links=LINKS) is None, "zadanie bez tytułu i id nie może wywalić renderowania"
    assert sharepoint_folder_url({"title": None}, links=LINKS) is None
    print("OK  brak dopasowania (także zadanie bez tytułu) zwraca None, nie wyjątek")


def test_format_done_task_renders_markdown_link():
    line = format_done_task({"task_id": "PRJ-0001", "title": "Sprawdź plik", "assignee": "asia"}, links=LINKS)
    assert f"[📁 materiały na SharePoint]({LINKS['PRJ-0001']})" in line, f"brak klikalnego linku Markdown w: {line}"
    assert line.startswith("   - Sprawdź plik (asia)"), "link nie może zastąpić tytułu ani wykonawcy"
    print("OK  pozycja z mapowaniem renderuje link Markdown obok tytułu")


def test_format_done_task_without_mapping_has_no_link():
    line = format_done_task({"task_id": "PRJ-0003", "title": "Zwiększ budżet", "assignee": "pawel"}, links=LINKS)
    assert line == "   - Zwiększ budżet (pawel)", f"pozycja bez mapowania musi zostać goła: {line}"
    print("OK  pozycja bez mapowania renderuje się bez linku")


def test_build_digest_uses_production_mapping():
    """build_digest() czyta stałą modułu, nie argument — podmieniamy ją na czas
    testu, żeby sprawdzić, że sekcja 'Zrobione' realnie przepuszcza linki."""
    original = digest_generator.SHAREPOINT_FOLDER_LINKS
    digest_generator.SHAREPOINT_FOLDER_LINKS = LINKS
    try:
        tasks = [
            {"task_id": "PRJ-0002", "title": "Magnapharm: commit poprawki", "status": "done", "assignee": "kacper"},
            {"task_id": "PRJ-0003", "title": "Zwiększ budżet kampanii", "status": "done", "assignee": "pawel"},
            {"task_id": "PRJ-0009", "title": "Stary temat", "status": "todo", "dueDate": "2026-08-01"},
        ]
        text = build_digest(split_tasks(tasks, today=date(2026, 8, 17)))
    finally:
        digest_generator.SHAREPOINT_FOLDER_LINKS = original

    assert f"[📁 materiały na SharePoint]({LINKS['magnapharm']})" in text
    assert "   - Zwiększ budżet kampanii (pawel)" in text.split("\n"), \
        "zadanie bez mapowania musi zostać w digeście, tylko bez linku"
    assert text.count("materiały na SharePoint") == 1, "link ma się pojawić tylko przy dopasowanej pozycji"
    print("OK  build_digest wstawia linki w sekcji 'Zrobione' i nie wywala się na pozycjach bez mapowania")


def test_production_mapping_has_only_absolute_https_urls():
    for key, url in digest_generator.SHAREPOINT_FOLDER_LINKS.items():
        assert url.startswith("https://"), f"wpis '{key}' nie jest bezwzględnym adresem https: {url}"
        assert " " not in url, f"wpis '{key}' ma spację w URL (link nie będzie klikalny): {url}"
    print(f"OK  wszystkie {len(digest_generator.SHAREPOINT_FOLDER_LINKS)} wpisów mapowania to poprawne adresy https bez spacji")


class _FakeClient:
    """Atrapa Projectly — śledzi create_task/post_comment, żeby sprawdzić GDZIE
    realnie ląduje digest (żywy bug 26.08.2026, znaleziony w audycie 27.08.2026:
    generate_digest publikował komentarz na zmyślonym task_id "DIGEST-ALL",
    który nigdy nie był tworzony jako realne zadanie — digest nigdy nie docierał
    do człowieka, mimo że kod nie rzucał żadnego wyjątku)."""
    def __init__(self, admin_project_id="ADMIN-PROJ"):
        self.created_tasks = []
        self.comments = []
        self._admin_project_id = admin_project_id

    def list_tasks(self, project_id=None):
        return []

    def create_task(self, title, description, assigned_to=None, project_id=None, **kwargs):
        task_id = f"DIGEST-TASK-{len(self.created_tasks) + 1:03d}"
        self.created_tasks.append({"task_id": task_id, "title": title, "project_id": project_id})
        return task_id

    def default_admin_project_id(self):
        return self._admin_project_id

    def post_comment(self, task_id, text):
        self.comments.append((task_id, text))
        return True


def _temp_ids_path():
    return Path(tempfile.mkdtemp()) / "digest_task_ids.json"


def test_generate_digest_posts_to_a_real_created_task_not_a_made_up_id():
    client = _FakeClient()
    path = _temp_ids_path()
    original = digest_generator.DIGEST_TASK_IDS_PATH
    digest_generator.DIGEST_TASK_IDS_PATH = path
    try:
        digest_generator.generate_digest(client=client, today=date(2026, 8, 17))
    finally:
        digest_generator.DIGEST_TASK_IDS_PATH = original

    assert len(client.created_tasks) == 1, "pierwsze wywołanie musi utworzyć REALNE zadanie-kanał"
    real_task_id = client.created_tasks[0]["task_id"]
    assert not real_task_id.startswith("DIGEST-ALL"), "task_id musi pochodzić z create_task, nie być zmyślony"
    assert len(client.comments) == 1
    assert client.comments[0][0] == real_task_id, "komentarz z digestem musi trafić na TO SAMO realne zadanie"
    print("OK  generate_digest publikuje na realnym zadaniu utworzonym przez create_task, nie na zmyślonym ID")


def test_digest_task_created_once_then_reused():
    client = _FakeClient()
    path = _temp_ids_path()
    original = digest_generator.DIGEST_TASK_IDS_PATH
    digest_generator.DIGEST_TASK_IDS_PATH = path
    try:
        digest_generator.generate_digest(client=client, today=date(2026, 8, 17))
        digest_generator.generate_digest(client=client, today=date(2026, 8, 18))
        digest_generator.generate_digest(client=client, today=date(2026, 8, 19))
    finally:
        digest_generator.DIGEST_TASK_IDS_PATH = original

    assert len(client.created_tasks) == 1, "zadanie-kanał tworzone RAZ, kolejne przebiegi tylko komentują"
    assert len(client.comments) == 3, "każdy przebieg dopisuje komentarz na tym samym zadaniu"
    assert all(tid == client.created_tasks[0]["task_id"] for tid, _ in client.comments)
    print("OK  zadanie-kanał digestu tworzone raz, kolejne przebiegi tylko komentują (nie mnożą zadań)")


def test_digest_fails_soft_without_any_project():
    client = _FakeClient(admin_project_id=None)
    path = _temp_ids_path()
    original = digest_generator.DIGEST_TASK_IDS_PATH
    digest_generator.DIGEST_TASK_IDS_PATH = path
    try:
        text = digest_generator.generate_digest(client=client, today=date(2026, 8, 17))
    finally:
        digest_generator.DIGEST_TASK_IDS_PATH = original

    assert len(client.created_tasks) == 0
    assert len(client.comments) == 0
    assert text, "digest jako tekst musi się nadal wygenerować, nawet gdy nie ma gdzie go opublikować"
    print("OK  brak project_id i default_admin_project -> fail-soft, digest zwrócony ale nie opublikowany")


if __name__ == "__main__":
    test_exact_task_id_wins_over_keyword()
    test_exact_title_match()
    test_category_keyword_is_case_insensitive()
    test_no_match_returns_none_without_error()
    test_format_done_task_renders_markdown_link()
    test_format_done_task_without_mapping_has_no_link()
    test_build_digest_uses_production_mapping()
    test_production_mapping_has_only_absolute_https_urls()
    test_generate_digest_posts_to_a_real_created_task_not_a_made_up_id()
    test_digest_task_created_once_then_reused()
    test_digest_fails_soft_without_any_project()
    print("\nWszystkie testy digest_generator przeszły.")
