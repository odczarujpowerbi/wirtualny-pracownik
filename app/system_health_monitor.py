"""
Monitor zdrowia MASZYNY (nie zadań) — pamięć RAM i czy oczekiwane skrypty
faktycznie działają. Odpowiedź na wprost zadane wymaganie: skrypt ma latać
cyklicznie (domyślnie co 2 minuty), widzieć stan pamięci i uruchomionych
procesów, i na tej podstawie sam podejmować decyzję (eskalować albo nie) —
bez czekania, aż człowiek zapyta.

Różnica względem tego, co już jest: `heartbeat.py`/`watchdog.py` sprawdzają
tylko, czy `runner_loop.py` sam o sobie regularnie "daje znać" (świeżość
pliku) — nie widzą realnego stanu maszyny (RAM, czy proces w ogóle żyje w
systemie operacyjnym, nie tylko czy napisał plik). Ten moduł patrzy o
poziom niżej, na sam system operacyjny, i uzupełnia (nie zastępuje)
watchdoga. Publikuje status TYM SAMYM mechanizmem co `live_status_publisher.py`
(`client.publish_status`, docelowo MCP `post_agent_status` — PLAN-MONITOROWANIE-
AGENTOW-WIRTUALNY-PRACOWNIK.md), pod osobną rolą "system-health", żeby nie
nadpisywać statusu roli-bota. Kształt payloadu (status ok/warning/critical +
issues) różni się od tego z `live_status_publisher.py` — normalizacja centralna
w `projectly_client.py._map_status_payload`, ten moduł nic nie zmienia.

Razem z `runner_loop.py --loop` (cykl zadań z Projectly) tworzy dokładnie
pętlę, o którą prosiłeś: jeden proces cyklicznie patrzy na stan maszyny i
decyduje/eskaluje, drugi cyklicznie pobiera i wykonuje zadania z Projectly
— oba niezależne, oba uruchamiane raz i działające same (Harmonogram
zadań Windows / cron / systemd, patrz INSTRUKCJA-WDROZENIA.md Krok 8 i
WDROZENIE-VPS-TESTOWE.md).

Wymaga pakietu `psutil` (dodany do requirements.txt) — to jedyny sposób,
żeby odczytać RAM/procesy identycznie na Windows i Linuksie bez pisania
osobnego kodu na każdy system.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import psutil
import yaml

from projectly_client import PRIORITY_PRIORYTET, get_client

THRESHOLDS_PATH = Path(__file__).parent / "config" / "health_thresholds.yaml"
STATE_PATH = Path(__file__).parent / "runs" / "system_health_state.json"


def load_thresholds(path=THRESHOLDS_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _today_key():
    return datetime.now(timezone.utc).date().isoformat()


def _load_state(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {"alert_tasks": {}}


def _save_state(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def list_running_scripts():
    """Zwraca nazwy plików .py widoczne w linii poleceń dowolnego
    uruchomionego procesu — 'jakie skrypty są uruchomione', dokładnie jak
    prosiłeś. Procesy, do których nie mamy uprawnień odczytu, są pomijane
    (nie wywalają całego skanu)."""
    found = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = proc.info["cmdline"] or []
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        for part in cmdline:
            if isinstance(part, str) and part.endswith(".py"):
                found.add(Path(part).name)
    return sorted(found)


def get_system_snapshot():
    mem = psutil.virtual_memory()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ram_total_gb": round(mem.total / (1024**3), 2),
        "ram_available_gb": round(mem.available / (1024**3), 2),
        "ram_available_percent": round(100 - mem.percent, 1),
        "running_scripts": list_running_scripts(),
    }


def evaluate_health(snapshot, thresholds):
    issues = []

    min_available = thresholds.get("min_available_ram_percent", 10)
    if snapshot["ram_available_percent"] < min_available:
        issues.append(
            f"Mało wolnej pamięci RAM: {snapshot['ram_available_percent']}% dostępne "
            f"(próg {min_available}%)."
        )

    for expected in thresholds.get("expected_scripts", []):
        if expected not in snapshot["running_scripts"]:
            issues.append(f"Oczekiwany skrypt nie działa: {expected}.")

    return {"status": "critical" if issues else "ok", "issues": issues}


def run_health_check(client=None, thresholds=None, state_path=STATE_PATH):
    client = client or get_client()
    thresholds = thresholds or load_thresholds()
    state = _load_state(state_path)

    import live_status_publisher

    snapshot = get_system_snapshot()
    health = evaluate_health(snapshot, thresholds)

    payload = {**snapshot, "status": health["status"], "issues": health["issues"],
               "update_interval_seconds": live_status_publisher._skonfigurowany_interwal(
                   "system_health_monitor", 120)}
    client.publish_status("system-health", payload)

    created_task_id = None
    # Deduplikacja PER DZIEŃ (ten sam wzorzec co kacper_monitor.py) — żywy bug
    # 26.08.2026, znaleziony w audycie: bez tego KAŻDY przebieg ze status=critical
    # tworzył NOWE zadanie w Projectly, nawet gdy poprzednie jeszcze nie zostało
    # obsłużone — 10 prawie identycznych "Alert: stan maszyny..." w 20 minut,
    # podczas gdy RAM spadał do wyczerpania (maszyna finalnie padła).
    dedup_key = f"critical:{_today_key()}"
    if health["status"] == "critical" and dedup_key not in state["alert_tasks"]:
        # create_task w realnym Projectly wymaga project_id; ten alert nie ma
        # naturalnego projektu źródłowego, więc bierzemy skonfigurowany
        # default_admin_project. Fail-closed: bez niego NIE zgadujemy projektu,
        # zostaje przy publish_status (widoczne w dashboardzie).
        admin_project_id = client.default_admin_project_id()
        if admin_project_id:
            created_task_id = client.create_task(
                title="Alert: stan maszyny wymaga sprawdzenia",
                description="Wykryte problemy:\n- " + "\n- ".join(health["issues"]),
                assigned_to=thresholds.get("alert_assignee", "pawel"),
                project_id=admin_project_id,
                # priorytet (29.08.2026, decyzja właściciela): realna awaria
                # maszyny ma być obsłużona najpierw, przed zwykłą pracą w kolejce.
                priority=PRIORITY_PRIORYTET,
            )
            state["alert_tasks"][dedup_key] = created_task_id
            _save_state(state, state_path)
        else:
            print("[system_health_monitor] Brak default_admin_project — NIE tworzę zadania w Projectly.")
    elif health["status"] == "ok" and dedup_key in state["alert_tasks"]:
        # Zdrowie wróciło do normy — kolejny epizod critical (nawet tego samego
        # dnia) ma prawo dostać NOWE zadanie, nie zlewać się z poprzednim.
        del state["alert_tasks"][dedup_key]
        _save_state(state, state_path)

    return {"snapshot": snapshot, "health": health, "created_task_id": created_task_id}


def main():
    import argparse
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Ciągła pętla zamiast jednego przebiegu")
    parser.add_argument("--interval", type=int, default=120, help="Sekundy między przebiegami (domyślnie 120 = 2 min)")
    args = parser.parse_args()

    if not args.loop:
        print(run_health_check())
        return

    print(f"Monitor zdrowia maszyny w trybie ciągłym, interwał {args.interval}s. Ctrl+C żeby zatrzymać.")
    try:
        while True:
            print(run_health_check())
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Zatrzymano ręcznie.")


if __name__ == "__main__":
    main()
