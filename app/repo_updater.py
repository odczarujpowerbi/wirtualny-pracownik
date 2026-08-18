"""
repo_updater.py — pobiera świeży kod z GitHub (git pull --ff-only) jako funkcja,
żeby dało się to wpiąć w scheduler (job `repo_update`).

Ta sama logika co aktualizuj-repo.bat, tylko schedulowalna: gdy włączysz ten job
w dashboardzie, VM sama pobiera nowy kod, a zaraz po tym `self_check` weryfikuje,
czy nic się nie zepsuło. Domyślnie WYŁĄCZONY (enabled: false) — automatyczne
pobieranie i uruchamianie kodu to świadoma decyzja (fail-closed): włącz dopiero,
gdy chcesz, żeby maszyna aktualizowała się bez Ciebie.

--ff-only: tylko czyste przewinięcie do przodu. Lokalne commity na VM zatrzymają
pull z jasnym błędem, zamiast tworzyć przypadkowy merge — VM ma konsumować kod,
nie tworzyć.
"""

import subprocess
from pathlib import Path

REPO_DIR = Path(__file__).parent.parent  # app/ -> korzeń repo (tam jest .git)


def run_update(runner=subprocess.run):
    """Pobiera zmiany z origin/main. runner wstrzykiwany w testach. Rzuca
    RuntimeError przy nieudanym pull (scheduler oznaczy przebieg jako error)."""
    proc = runner(
        ["git", "pull", "--ff-only", "origin", "main"],
        cwd=str(REPO_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    output = (proc.stdout or "").strip()
    print(output or "(git nie wypisał nic)")
    if proc.returncode != 0:
        raise RuntimeError(f"git pull nie powiódł się: {(proc.stderr or '').strip()[:300]}")
    return {"output": output}


if __name__ == "__main__":
    print(run_update())
