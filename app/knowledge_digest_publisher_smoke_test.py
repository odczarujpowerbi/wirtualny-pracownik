"""
Test dymny knowledge_digest_publisher.py. Bez sieci: _FakeClient podmienia
get_week_report/._mcp.call_tool, pliki .env sa tymczasowe. Wpina sie
automatycznie w self_check.py.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import knowledge_digest_publisher as kdp

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)

SAMPLE_REPORT = {
    "weekOffset": 0,
    "range": {"from": "2026-08-17", "to": "2026-08-23"},
    "summary": {"completedCount": 99, "stuckCount": 48, "activeBlockerCount": 2},
    "perPerson": [
        {"name": "AI - Dev", "completedCount": 69, "inProgressCount": 18, "stuckCount": 0},
        {"name": "AI - Marketing", "completedCount": 2, "inProgressCount": 0, "stuckCount": 0},
        {"name": "Paweł", "completedCount": 6, "inProgressCount": 9, "stuckCount": 36},
    ],
    "completed": [
        {"title": "Zadanie A", "project": "Administracyjne", "assignees": ["AI - Dev"]},
        {"title": "Zadanie B", "project": "Marketing", "assignees": ["AI - Marketing"]},
        {"title": "Zadanie C", "project": "Administracyjne", "assignees": ["Paweł"]},
    ],
}


class _FakeClient:
    def __init__(self, next_id="KNOW-0001"):
        self.created = []
        self.updated = []
        self._next_id = next_id

    def get_week_report(self, week_offset=0):
        return SAMPLE_REPORT

    def create_knowledge(self, title, content, scope="self", tags=None, links=None):
        self.created.append({"title": title, "content": content, "scope": scope})
        return {"id": self._next_id}

    def update_knowledge(self, knowledge_id, title=None, content=None, tags=None, links=None):
        self.updated.append({"knowledgeId": knowledge_id, "title": title, "content": content})
        return {"id": knowledge_id}


def test_build_digest_text_shows_own_stats_and_org_context():
    text = kdp.build_digest_text(_FakeClient(), "dev", now=NOW)
    assert "AI - Dev" in text
    assert "Wykonane: 69" in text
    assert "Wykonane łącznie: 99" in text
    assert "Zadanie A" in text
    assert "Zadanie C" not in text, "digest AI - Dev nie powinien pokazywac cudzych zadan"
    assert "Rozbicie po osobach" not in text, "rozbicie pelnej organizacji tylko dla roli zarzad"
    print("OK  build_digest_text('dev') -> wlasne liczby + kontekst organizacji, bez cudzych zadan")


def test_build_digest_text_zarzad_includes_full_breakdown():
    text = kdp.build_digest_text(_FakeClient(), "zarzad", now=NOW)
    assert "Rozbicie po osobach i botach" in text
    assert "Paweł: wykonane 6" in text
    print("OK  build_digest_text('zarzad') -> pelne rozbicie po osobach/botach")


def test_build_digest_text_no_own_row_still_works():
    report = {**SAMPLE_REPORT, "perPerson": []}

    class _NoOwnRow(_FakeClient):
        def get_week_report(self, week_offset=0):
            return report

    text = kdp.build_digest_text(_NoOwnRow(), "dev", now=NOW)
    assert "Brak zadań przypisanych w tym tygodniu." in text
    print("OK  brak wlasnego wiersza w perPerson -> czytelny komunikat, bez wyjatku")


def test_load_agent_env_missing_folder_returns_none():
    tmp = Path(tempfile.mkdtemp())
    assert kdp._load_agent_env("dev", agents_dir=tmp) is None
    print("OK  brak folderu roli -> _load_agent_env zwraca None (fail-soft)")


def test_load_agent_env_reads_present_file():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "dev").mkdir()
    (tmp / "dev" / ".env").write_text(
        "PROJECTLY_API_KEY=prj_test123\nPROJECTLY_BASE_URL=https://example.test/api/mcp\n",
        encoding="utf-8",
    )
    env = kdp._load_agent_env("dev", agents_dir=tmp)
    assert env == {"PROJECTLY_API_KEY": "prj_test123", "PROJECTLY_BASE_URL": "https://example.test/api/mcp"}
    print("OK  _load_agent_env czyta obecny plik .env roli")


def test_publish_to_knowledge_base_creates_then_updates_same_entry():
    tmp_ids = Path(tempfile.mkdtemp()) / "knowledge_entry_ids.json"
    client = _FakeClient(next_id="KNOW-0007")

    ok1 = kdp._publish_to_knowledge_base(client, "dev", "Tytuł", "Treść 1", entry_ids_path=tmp_ids)
    assert ok1 is True
    assert client.created == [{"title": "Tytuł", "content": "Treść 1", "scope": "self"}]
    assert client.updated == [], "pierwszy przebieg -> create, nie update"
    assert json.loads(tmp_ids.read_text(encoding="utf-8")) == {"dev": "KNOW-0007"}

    ok2 = kdp._publish_to_knowledge_base(client, "dev", "Tytuł", "Treść 2", entry_ids_path=tmp_ids)
    assert ok2 is True
    assert len(client.created) == 1, "drugi przebieg NIE powinien tworzyć nowego wpisu"
    assert client.updated == [{"knowledgeId": "KNOW-0007", "title": "Tytuł", "content": "Treść 2"}]
    print("OK  pierwszy przebieg create_knowledge, kolejne update_knowledge tego samego wpisu (id z pliku)")


def test_run_knowledge_digest_skips_role_without_token():
    tmp = Path(tempfile.mkdtemp())
    (tmp / "dev").mkdir()
    (tmp / "dev" / ".env").write_text(
        "PROJECTLY_API_KEY=prj_test123\nPROJECTLY_BASE_URL=https://example.test/api/mcp\n",
        encoding="utf-8",
    )
    # "marketing" i "zarzad" celowo bez folderu - maja wyjsc jako brak_tokenu,
    # nie failowac calego przebiegu. "dev" tez pominiety w tym tescie (uzylby
    # prawdziwego ProjectlyClient z siecia) - testowany osobno przez _load_agent_env.
    results = kdp.run_knowledge_digest(roles=["marketing", "zarzad"], agents_dir=tmp)
    assert results == {"marketing": "brak_tokenu", "zarzad": "brak_tokenu"}
    print("OK  run_knowledge_digest pomija role bez tokenu, nie wywala calego przebiegu")


if __name__ == "__main__":
    test_build_digest_text_shows_own_stats_and_org_context()
    test_build_digest_text_zarzad_includes_full_breakdown()
    test_build_digest_text_no_own_row_still_works()
    test_load_agent_env_missing_folder_returns_none()
    test_load_agent_env_reads_present_file()
    test_publish_to_knowledge_base_creates_then_updates_same_entry()
    test_run_knowledge_digest_skips_role_without_token()
    print("\nWszystkie testy knowledge_digest_publisher przeszly.")
