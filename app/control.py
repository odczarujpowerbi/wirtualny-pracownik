"""
Sterowanie agentem z panelu operatora (M3 / OPS-01). Trzy stany:

  running  — pracuje normalnie
  paused   — miękkie wstrzymanie: NIE podejmuje NOWEJ pracy, stan zachowany,
             RESUME wznawia jednym kliknięciem (flaga runs/PAUSE.flag)
  stopped  — twardy wyłącznik awaryjny (kill_switch.py, runs/STOP.flag) — ostatnia
             linia obrony; START (deactivate) zdejmuje

STOP ma priorytet nad PAUSE. Pętle (job_scheduler, runner_loop, notebook_intake)
pytają `should_run_new_work()` — bieżące, już trwające zadanie kończy się samo,
nowego nie zaczynamy (bezpieczne zatrzymanie wg PLAN-WDROZENIA.md sekcja 17).

`should_run_new_work()` dolicza też budżet dobowy (cost_tracker.budget_state) —
przy 'warning' (domyślnie 92% limitu) lub 'exceeded' też nie zaczynamy nowej
pracy, bez potrzeby ręcznego STOP/START (samo-czyszczące następnego dnia).
"""

from pathlib import Path

import cost_tracker
import kill_switch

PAUSE_FLAG_PATH = Path(__file__).parent / "runs" / "PAUSE.flag"


def pause(reason="Wstrzymano z panelu operatora."):
    PAUSE_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    PAUSE_FLAG_PATH.write_text(reason or "Wstrzymano.", encoding="utf-8")


def resume():
    PAUSE_FLAG_PATH.unlink(missing_ok=True)


def is_paused():
    return PAUSE_FLAG_PATH.exists()


def pause_reason():
    return PAUSE_FLAG_PATH.read_text(encoding="utf-8").strip() if PAUSE_FLAG_PATH.exists() else ""


def state():
    """running | paused | stopped (STOP ma priorytet nad PAUSE)."""
    if kill_switch.is_active():
        return "stopped"
    if is_paused():
        return "paused"
    return "running"


def should_run_new_work():
    """Czy wolno podjąć NOWĄ pracę — fałsz przy STOP, PAUSE, albo budżecie
    dobowym w stanie 'warning'/'exceeded' (cost_tracker.budget_state — trwające
    zadanie kończy się samo, tylko nowe nie startują; self-healing, wraca do
    'ok' bez ręcznego 'start', gdy budżet się odnowi następnego dnia)."""
    if kill_switch.is_active() or is_paused():
        return False
    return cost_tracker.budget_state()["level"] == "ok"


def apply(action):
    """Wykonuje akcję operatora. Zwraca (nowy_stan, komunikat). Nieznana akcja -> ValueError."""
    if action == "pause":
        pause()
        return state(), "Wstrzymano — agent nie podejmuje nowej pracy."
    if action == "resume":
        resume()
        return state(), "Wznowiono."
    if action == "stop":
        kill_switch.activate("Zatrzymano z panelu operatora.")
        return state(), "Zatrzymano (kill switch)."
    if action == "start":
        kill_switch.deactivate()
        return state(), "Zdjęto zatrzymanie."
    raise ValueError(f"Nieznana akcja '{action}' (dozwolone: pause/resume/stop/start).")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        new_state, msg = apply(sys.argv[1])
        print(f"{msg} Stan: {new_state}")
    else:
        print("Stan:", state(), "| pause:", pause_reason() or "-", "| stop:", kill_switch.reason() or "-")
