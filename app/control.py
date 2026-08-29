"""
Sterowanie agentem z panelu operatora (M3 / OPS-01). Trzy stany:

  running  — pracuje normalnie
  paused   — miękkie wstrzymanie: NIE podejmuje NOWEJ pracy, stan zachowany,
             RESUME wznawia jednym kliknięciem (flaga runs/PAUSE<_rola>.flag)
  stopped  — twardy wyłącznik awaryjny (kill_switch.py, runs/STOP.flag) — ostatnia
             linia obrony; START (deactivate) zdejmuje

STOP ma priorytet nad PAUSE. Pętle (job_scheduler, runner_loop, notebook_intake)
pytają `should_run_new_work()` — bieżące, już trwające zadanie kończy się samo,
nowego nie zaczynamy (bezpieczne zatrzymanie wg PLAN-WDROZENIA.md sekcja 17).

`should_run_new_work()` dolicza też budżet dobowy (cost_tracker.budget_state) —
przy 'warning' (domyślnie 92% limitu) lub 'exceeded' też nie zaczynamy nowej
pracy, bez potrzeby ręcznego STOP/START (samo-czyszczące następnego dnia).

PAUZA JEST ROLO-ŚWIADOMA (29.08.2026, decyzja właściciela: "wyłączenie agenta"
ma dotyczyć JEDNEGO bota, nie wszystkich naraz). Wcześniej jeden globalny plik
PAUSE.flag pauzował WSZYSTKIE procesy (dev/checker/marketing/zarząd) na tej
maszynie naraz, bo wszystkie czytają ten sam katalog runs/ — pauza z dashboardu
dla jednego bota cicho wstrzymywała resztę. role=None (domyślne wszędzie) ->
rola BIEŻĄCEGO procesu (env_bootstrap._current_role()), więc KAŻDY dotychczasowy
call site (runner_loop/job_scheduler/notebook_intake/remote_control, wszystkie
bez argumentu) automatycznie skaluje się do WŁASNEJ roli bez zmiany ani jednej
linii poza tym plikiem. Jawny `role=` istnieje dla dashboard.py — panel operatora
działa pod JEDNĄ rolą procesu, ale ma pokazywać/przełączać pauzę WSZYSTKICH
botów na maszynie.

kill_switch zostaje GLOBALNY (nie per rola, celowo BEZ zmian tutaj) — to
prawdziwy awaryjny wyłącznik, ma zatrzymać WSZYSTKO na maszynie na raz, nie
jednego bota.
"""

from pathlib import Path

import cost_tracker
import env_bootstrap
import kill_switch

RUNS_DIR = Path(__file__).parent / "runs"


def _pause_flag_path(role=None):
    role = role or env_bootstrap._current_role()
    suffix = "" if role == "dev" else f"_{role}"
    return RUNS_DIR / f"PAUSE{suffix}.flag"


def pause(reason="Wstrzymano z panelu operatora.", role=None):
    path = _pause_flag_path(role)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason or "Wstrzymano.", encoding="utf-8")


def resume(role=None):
    _pause_flag_path(role).unlink(missing_ok=True)


def is_paused(role=None):
    return _pause_flag_path(role).exists()


def pause_reason(role=None):
    path = _pause_flag_path(role)
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""


def state(role=None):
    """running | paused | stopped (STOP ma priorytet nad PAUSE)."""
    if kill_switch.is_active():
        return "stopped"
    if is_paused(role):
        return "paused"
    return "running"


def should_run_new_work(role=None):
    """Czy wolno podjąć NOWĄ pracę — fałsz przy STOP, PAUSE (TEJ roli), albo
    budżecie dobowym w stanie 'warning'/'exceeded' (cost_tracker.budget_state —
    trwające zadanie kończy się samo, tylko nowe nie startują; self-healing,
    wraca do 'ok' bez ręcznego 'start', gdy budżet się odnowi następnego dnia).
    Budżet dobowy jest współdzielony (jeden koszt AI na całą maszynę/subskrypcję),
    więc celowo NIE jest tu rolo-świadomy jak pauza."""
    if kill_switch.is_active() or is_paused(role):
        return False
    return cost_tracker.budget_state()["level"] == "ok"


def apply(action, role=None):
    """Wykonuje akcję operatora. Zwraca (nowy_stan, komunikat). Nieznana akcja ->
    ValueError. role=None -> własna rola procesu (pause/resume); stop/start
    (kill_switch) zostają globalne bez względu na `role`."""
    if action == "pause":
        pause(role=role)
        return state(role), "Wstrzymano — agent nie podejmuje nowej pracy."
    if action == "resume":
        resume(role=role)
        return state(role), "Wznowiono."
    if action == "stop":
        kill_switch.activate("Zatrzymano z panelu operatora.")
        return state(role), "Zatrzymano (kill switch)."
    if action == "start":
        kill_switch.deactivate()
        return state(role), "Zdjęto zatrzymanie."
    raise ValueError(f"Nieznana akcja '{action}' (dozwolone: pause/resume/stop/start).")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        rola = sys.argv[2] if len(sys.argv) > 2 else None
        new_state, msg = apply(sys.argv[1], role=rola)
        print(f"{msg} Stan: {new_state}")
    else:
        print("Stan:", state(), "| pause:", pause_reason() or "-", "| stop:", kill_switch.reason() or "-")
