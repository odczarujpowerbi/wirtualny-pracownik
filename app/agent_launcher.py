"""
Jedno miejsce, które wie JAK odpalić proces bota danej roli na tej maszynie —
mapa rola -> plik .bat plus samo uruchomienie procesu.

Wyodrębnione z dashboard.py 01.09.2026, kiedy drugi wywołujący (agent_supervisor.py,
nadzorca startujący boty na podstawie statusu zadania sterującego w Projectly)
potrzebował tego samego. Nadzorca ma być lekki i bezobsługowy — import
dashboard.py ciągnąłby za sobą serwer HTTP, notebook_intake, usage_monitor i
resztę panelu operatora, więc mapa .bat-ów wylądowała tutaj zamiast być
skopiowana do drugiego pliku.

dashboard.py sięga po te nazwy przez moduł (agent_launcher.AGENT_BAT_FILES),
nie przez `from ... import` — dzięki temu podmiana atrapą w testach dymnych
działa dla WSZYSTKICH wywołujących naraz, w jednym miejscu.
"""

import subprocess
import sys
from pathlib import Path

import scheduler_lock

# Repo root = katalog NADRZĘDNY wobec app/ (ten plik jest w app/, .bat-y w
# korzeniu repo). "dev" przemianowany z "start-agent.bat" na "start-agent-dev.bat"
# 29.08.2026 (spójność nazw z checker/marketing/zarząd).
REPO_ROOT = Path(__file__).parent.parent
AGENT_BAT_FILES = {
    "dev": REPO_ROOT / "start-agent-dev.bat",
    "checker": REPO_ROOT / "start-agent-checker.bat",
    "marketing": REPO_ROOT / "start-agent-marketing.bat",
    "zarzad": REPO_ROOT / "start-agent-zarzad.bat",
}


def _launch_process(cmd, cwd):
    """Jedyne miejsce faktycznie odpalające nowy proces — wyodrębnione, żeby
    testy dymne mogły to podmienić atrapą zamiast naprawdę spawnować proces
    (ten sam wzorzec co repo_auto_improver._run/agentic_worker._run).
    DETACHED_PROCESS + CREATE_NO_WINDOW (tylko Windows): proces przeżywa
    zamknięcie dashboardu/nadzorcy i nie otwiera widocznego okna konsoli —
    ma działać w tle jak uruchomiony przez Harmonogram zadań."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(cmd, cwd=str(cwd), **kwargs)


def start_agent(role):
    """Odpala proces job_scheduler.py dla WSKAZANEJ roli (przez jej .bat),
    jeśli jeszcze nie działa. Zwraca {"started": bool, "message": str} —
    nigdy nie rzuca, błąd trafia do message (ten sam wzorzec co _run_safely)."""
    if role not in AGENT_BAT_FILES:
        return {"started": False, "message": f"Nieznana rola '{role}'."}
    if scheduler_lock.is_running(role):
        return {"started": False, "message": f"Agent '{role}' już działa."}
    bat_path = AGENT_BAT_FILES[role]
    if not bat_path.exists():
        return {"started": False, "message": f"Brak pliku startowego: {bat_path}"}
    try:
        _launch_process(["cmd", "/c", str(bat_path)], cwd=REPO_ROOT)
    except OSError as exc:
        return {"started": False, "message": f"Nie udało się uruchomić agenta '{role}': {exc}"}
    return {"started": True, "message": f"Uruchamiam agenta '{role}'…"}
