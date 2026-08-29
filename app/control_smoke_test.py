"""
Test dymny sterowania agentem (M3 / OPS-01): przejścia stanów running/paused/stopped,
priorytet STOP nad PAUSE, should_run_new_work oraz odrzucenie nieznanej akcji.

Podmienia ścieżki flag na TYMCZASOWE — nie dotyka prawdziwych runs/STOP.flag i
runs/PAUSE.flag, więc nie wpływa na ewentualnie działającego agenta. Wpina się
automatycznie w self_check.py.
"""

import tempfile
from pathlib import Path

import control
import kill_switch


def _isolate_flags():
    tmp = Path(tempfile.mkdtemp())
    control.RUNS_DIR = tmp
    kill_switch.STOP_FLAG_PATH = tmp / "STOP.flag"
    # should_run_new_work() dolicza budżet (cost_tracker.budget_state, żywa
    # runs/state.db) — testy pause/stop mają sprawdzać TYLKO logikę pause/stop,
    # więc budżet zaślepiamy na 'ok', żeby nie zależały od realnego kosztu
    # nabitego na tej maszynie dzisiaj.
    _stub_budget("ok")


def _stub_budget(level, percent=0.0, total=0.0, limit=20.0):
    control.cost_tracker.budget_state = lambda *a, **kw: {
        "level": level, "total": total, "limit": limit, "percent": percent,
    }


def test_pause_resume():
    _isolate_flags()
    assert control.state() == "running", control.state()
    assert control.should_run_new_work() is True

    control.apply("pause")
    assert control.state() == "paused", control.state()
    assert control.should_run_new_work() is False, "PAUSE musi wstrzymać nową pracę"

    control.apply("resume")
    assert control.state() == "running", control.state()
    assert control.should_run_new_work() is True
    print("OK  pause -> paused (blokuje nową pracę) -> resume -> running")


def test_stop_priorytet_nad_pause():
    _isolate_flags()
    control.apply("pause")
    control.apply("stop")
    assert control.state() == "stopped", "STOP ma priorytet nad PAUSE"
    assert control.should_run_new_work() is False

    control.apply("start")  # zdejmuje STOP; PAUSE nadal aktywny
    assert control.state() == "paused", "po zdjęciu STOP wraca wcześniejszy PAUSE"
    control.apply("resume")
    assert control.state() == "running"
    print("OK  STOP > PAUSE; start zdejmuje STOP, PAUSE zostaje aż do resume")


def test_budget_blocks_new_work():
    _isolate_flags()
    assert control.state() == "running"
    assert control.should_run_new_work() is True, "budżet 'ok' nie blokuje"

    _stub_budget("warning", percent=93.0)
    assert control.state() == "running", "warning nie zmienia stanu running/paused/stopped"
    assert control.should_run_new_work() is False, "budżet 'warning' (92%+) musi wstrzymać nową pracę"

    _stub_budget("exceeded", percent=104.0)
    assert control.should_run_new_work() is False, "budżet 'exceeded' musi wstrzymać nową pracę"

    _stub_budget("ok")
    assert control.should_run_new_work() is True, "powrót do 'ok' odblokowuje bez ręcznego start"
    print("OK  budżet warning/exceeded wstrzymuje nową pracę, 'ok' odblokowuje samoczynnie")


def test_pauza_rolo_swiadoma():
    """Żywy bug znaleziony 29.08.2026 (żądanie właściciela: "wyłączenie agenta
    oznacza, że nie przyjmuje zadań" — o JEDNYM agencie): jeden globalny plik
    PAUSE.flag pauzował WSZYSTKIE role naraz. Pauza roli 'checker' NIE MOŻE
    wpływać na rolę 'dev', i odwrotnie."""
    _isolate_flags()
    assert control.state(role="dev") == "running"
    assert control.state(role="checker") == "running"

    control.apply("pause", role="checker")
    assert control.state(role="checker") == "paused", "checker ma być wstrzymany"
    assert control.state(role="dev") == "running", "dev NIE MOŻE zostać wstrzymany pauzą checkera"
    assert control.should_run_new_work(role="checker") is False
    assert control.should_run_new_work(role="dev") is True

    control.apply("resume", role="checker")
    assert control.state(role="checker") == "running"
    print("OK  pauza jednej roli (checker) nie wpływa na inną rolę (dev)")


def test_unknown_action():
    _isolate_flags()
    try:
        control.apply("frobnicate")
        raised = False
    except ValueError:
        raised = True
    assert raised, "nieznana akcja musi rzucić ValueError"
    print("OK  nieznana akcja odrzucona (ValueError)")


if __name__ == "__main__":
    test_pause_resume()
    test_stop_priorytet_nad_pause()
    test_budget_blocks_new_work()
    test_pauza_rolo_swiadoma()
    test_unknown_action()
    print("\nWszystkie testy sterowania przeszły.")
