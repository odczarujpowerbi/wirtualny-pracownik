"""
Test dymny monitora zuzycia Claude (estymacja "ile zadan jeszcze"). Pokrywa:
- window_usage liczy tylko rekordy w oknie 5h (starsze pomija),
- today_usage sumuje calosc,
- summary zwraca estymacje zadan wzgledem budzetu,
- brak pliku -> available:false (lagodna degradacja).

Uzywa fixture w pliku tymczasowym + jawnego `now` (deterministycznie).
Wpina sie automatycznie w self_check.py.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import usage_monitor

NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)


def _fixture():
    tmp = Path(tempfile.mkdtemp()) / "today.json"
    data = {"data": [
        {"timestamp": "2026-08-19T11:30:00.000Z", "usage": {}, "costUSD": 2.0, "model": "claude-opus-4-8"},   # w oknie 5h
        {"timestamp": "2026-08-19T09:00:00.000Z", "usage": {}, "costUSD": 1.0, "model": "claude-opus-4-8"},   # w oknie 5h
        {"timestamp": "2026-08-19T03:00:00.000Z", "usage": {}, "costUSD": 5.0, "model": "claude-opus-4-8"},   # POZA oknem 5h
    ]}
    tmp.write_text(json.dumps(data), encoding="utf-8")
    return tmp


def test_window_excludes_old():
    recs = usage_monitor.load_records(_fixture())
    w = usage_monitor.window_usage(recs, hours=5, now=NOW)
    assert w["calls"] == 2, w          # tylko 2 rekordy w ostatnich 5h
    assert abs(w["cost_usd"] - 3.0) < 1e-6, w
    print("OK  window_usage liczy tylko okno 5h (starsze pomija)")


def test_today_sums_all():
    recs = usage_monitor.load_records(_fixture())
    t = usage_monitor.today_usage(recs)
    assert t["calls"] == 3 and abs(t["cost_usd"] - 8.0) < 1e-6, t
    print("OK  today_usage sumuje calosc")


def test_summary_estimates():
    s = usage_monitor.summary(path=_fixture(), block_budget_usd=13.0, now=NOW)
    assert s["available"] is True, s
    assert abs(s["block_5h_usd"] - 3.0) < 1e-6, s
    # budzet 13 - 3 zuzyte = 10 wolne; est_tasks = 10 / avg_task_cost
    assert s["estimated_tasks_remaining"] is not None and s["estimated_tasks_remaining"] > 0, s
    assert s["block_budget_used_pct"] is not None, s
    print(f"OK  summary estymuje zadania (pozostalo ~{s['estimated_tasks_remaining']}, avg=${s['avg_task_cost_usd']})")


def test_missing_file():
    s = usage_monitor.summary(path=Path(tempfile.mkdtemp()) / "nie_ma.json", now=NOW)
    assert s["available"] is False, s
    print("OK  brak pliku -> available:false (lagodna degradacja)")


def test_over_threshold_wymaga_swiadomej_konfiguracji():
    """Zywy przypadek 29.08.2026: DEFAULT_BLOCK_BUDGET_USD (40 USD) na realnej
    maszynie dawal 198% (sesja realnie kosztowniejsza niz ten placeholder) -
    over_threshold() MUSI zostac False, dopoki wlasciciel nie ustawi realnego
    budzetu w BLOCK_BUDGET_PATH - inaczej wlaczenie tej funkcji zatrzymaloby
    boty na zgadanym progu, bez swiadomej decyzji."""
    original_path = usage_monitor.BLOCK_BUDGET_PATH
    tmp_dir = Path(tempfile.mkdtemp())
    try:
        usage_monitor.BLOCK_BUDGET_PATH = tmp_dir / "usage_block_budget_usd.txt"

        podsumowanie_wysokie = {"available": True, "block_budget_used_pct": 198.2}
        assert usage_monitor.over_threshold(podsumowanie_wysokie) is False, \
            "bez skonfigurowanego budzetu - NIGDY nie blokuje, nawet przy 198%"

        usage_monitor.BLOCK_BUDGET_PATH.write_text("15.0", encoding="utf-8")
        assert usage_monitor.over_threshold(podsumowanie_wysokie) is True, \
            "po skonfigurowaniu budzetu - 198% >= prog (85%) -> True"

        podsumowanie_niskie = {"available": True, "block_budget_used_pct": 10.0}
        assert usage_monitor.over_threshold(podsumowanie_niskie) is False, \
            "skonfigurowany budzet, ale ponizej progu -> False"

        assert usage_monitor.over_threshold({"available": False}) is False, \
            "available=False -> zawsze False, niezaleznie od konfiguracji"
    finally:
        usage_monitor.BLOCK_BUDGET_PATH = original_path
    print("OK  over_threshold blokuje WYLACZNIE po swiadomej konfiguracji budzetu okna 5h")


if __name__ == "__main__":
    test_window_excludes_old()
    test_today_sums_all()
    test_summary_estimates()
    test_missing_file()
    test_over_threshold_wymaga_swiadomej_konfiguracji()
    print("\nWszystkie testy monitora zuzycia przeszly.")
