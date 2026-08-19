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
    control.PAUSE_FLAG_PATH = tmp / "PAUSE.flag"
    kill_switch.STOP_FLAG_PATH = tmp / "STOP.flag"


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
    test_unknown_action()
    print("\nWszystkie testy sterowania przeszły.")
