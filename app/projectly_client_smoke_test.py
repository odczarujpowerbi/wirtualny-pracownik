"""
Test dymny MockProjectlyClient._load/_save: samo-leczenie z uszkodzonego JSON
i rotacja mock_comments.json (żywy incydent 21.08.2026 — dwa procesy scheduler
pisały równocześnie do runs/mock_comments.json, plik narósł do 6+ MB i
uszkodził się, "Extra data" wywalało runner_loop na każdym cyklu). Operuje na
plikach TYMCZASOWYCH, nie dotyka prawdziwego runs/mock_comments.json.
"""

import json
import tempfile
from pathlib import Path

from projectly_client import MAX_COMMENTS_PER_TASK, MockProjectlyClient


def _client_with(path):
    client = MockProjectlyClient()
    client._comments_path = path
    return client


def test_self_heal_from_corrupt_json():
    tmp = Path(tempfile.mkdtemp())
    bad = tmp / "mock_comments.json"
    bad.write_text('{"PRJ-0001": ["a"]} extra garbage', encoding="utf-8")

    client = _client_with(bad)
    assert client.get_comments("PRJ-0001") == [], "plik uszkodzony musi być traktowany jak brak danych"

    client.post_comment("PRJ-0001", "hello")
    data = json.loads(bad.read_text(encoding="utf-8"))
    assert data == {"PRJ-0001": ["hello"]}, "zapis po samo-leczeniu musi być czystym, poprawnym JSON"
    print("OK  odczyt uszkodzonego JSON nie wywala runnera, zapis go naprawia")


def test_atomic_save_no_leftover_tmp():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "mock_comments.json"
    client = _client_with(path)

    client.post_comment("X", "msg")
    leftovers = list(tmp.glob("*.tmp*"))
    assert leftovers == [], f"zapis atomowy nie powinien zostawiać plików tymczasowych: {leftovers}"
    print("OK  zapis atomowy (tmp + os.replace) nie zostawia plików tymczasowych")


def test_comments_rotate_and_cap():
    tmp = Path(tempfile.mkdtemp())
    path = tmp / "mock_comments.json"
    client = _client_with(path)

    total = MAX_COMMENTS_PER_TASK + 50
    for i in range(total):
        client.post_comment("X", f"msg{i}")

    thread = client.get_comments("X")
    assert len(thread) == MAX_COMMENTS_PER_TASK, f"lista powinna być przycięta do {MAX_COMMENTS_PER_TASK}, jest {len(thread)}"
    assert thread[0] == f"msg{total - MAX_COMMENTS_PER_TASK}", "musi zostać NAJNOWSZY ogon, nie początek"
    assert thread[-1] == f"msg{total - 1}"
    print(f"OK  komentarze przycięte do ostatnich {MAX_COMMENTS_PER_TASK} (bez nieograniczonego wzrostu pliku)")


def test_mock_has_default_admin_project_id():
    # ProjectlyClient.create_task realnego klienta wymaga project_id (żywy
    # incydent 21.08.2026 — kacper_monitor/system_health_monitor wywalały się
    # na tym przy zadaniach bez naturalnego projektu). Mock musi wystawiać ten
    # sam interfejs, żeby kod wywołujący był identyczny na mocku i na żywo.
    client = MockProjectlyClient()
    assert client.default_admin_project_id(), "mock musi zwracac niepusty project_id"
    print("OK  MockProjectlyClient.default_admin_project_id() zwraca stały mockowy id")


if __name__ == "__main__":
    test_self_heal_from_corrupt_json()
    test_atomic_save_no_leftover_tmp()
    test_comments_rotate_and_cap()
    test_mock_has_default_admin_project_id()
    print("\nWszystkie testy MockProjectlyClient przeszły.")
