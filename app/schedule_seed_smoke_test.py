"""
Test dymny seedowania/domergowania harmonogramu (systemowy fix konfliktu git pull:
schedule.yaml LIVE poza gitem, schedule.default.yaml SZABLON w gicie). Pokrywa:
- brak LIVE -> seed z SZABLONU,
- SZABLON dostaje nowy job -> domergowany do LIVE po nazwie,
- lokalny przelacznik (enabled) istniejacego joba NIE jest kasowany przy domergowaniu.

Podmienia globale SCHEDULE_PATH/DEFAULT_SCHEDULE_PATH na pliki tymczasowe - nie
dotyka prawdziwego config/. Wpina sie automatycznie w self_check.py.
"""

import tempfile
from pathlib import Path

import yaml

import job_scheduler as js


def _write_default(path, names):
    jobs = [{"name": n, "module": "m", "function": "f", "interval_seconds": 30, "enabled": True} for n in names]
    Path(path).write_text(yaml.safe_dump({"jobs": jobs}, allow_unicode=True), encoding="utf-8")


def _use_temp():
    tmp = Path(tempfile.mkdtemp())
    js.SCHEDULE_PATH = tmp / "schedule.yaml"
    js.DEFAULT_SCHEDULE_PATH = tmp / "schedule.default.yaml"


def test_seed_when_missing():
    _use_temp()
    _write_default(js.DEFAULT_SCHEDULE_PATH, ["a", "b"])
    assert not js.SCHEDULE_PATH.exists(), "na start LIVE nie istnieje"
    js._ensure_live_schedule()
    names = sorted(j["name"] for j in js._read_jobs(js.SCHEDULE_PATH))
    assert names == ["a", "b"], names
    print("OK  brak LIVE -> seed z SZABLONU")


def test_merge_new_job_keeps_local_toggle():
    _use_temp()
    _write_default(js.DEFAULT_SCHEDULE_PATH, ["a", "b"])
    js._ensure_live_schedule()
    # lokalna zmiana: wylacz 'a' (jawna sciezka, bo default arg zwiazany przy imporcie)
    js.update_job("a", {"enabled": False}, path=js.SCHEDULE_PATH)
    # SZABLON dostaje nowy job 'c'
    _write_default(js.DEFAULT_SCHEDULE_PATH, ["a", "b", "c"])
    js._ensure_live_schedule()
    live = {j["name"]: j for j in js._read_jobs(js.SCHEDULE_PATH)}
    assert set(live) == {"a", "b", "c"}, list(live)
    assert live["a"]["enabled"] is False, "lokalny przelacznik 'a' musi przetrwac domergowanie"
    print("OK  nowy job z SZABLONU domergowany; lokalny przelacznik zachowany")


if __name__ == "__main__":
    test_seed_when_missing()
    test_merge_new_job_keeps_local_toggle()
    print("\nWszystkie testy seedowania harmonogramu przeszly.")
