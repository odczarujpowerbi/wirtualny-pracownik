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

from datetime import datetime, timezone
from pathlib import Path

import psutil
import yaml

from projectly_client import get_client

THRESHOLDS_PATH = Path(__file__).parent / "config" / "health_thresholds.yaml"


def load_thresholds(path=THRESHOLDS_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


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


def run_health_check(client=None, thresholds=None):
    client = client or get_client()
    thresholds = thresholds or load_thresholds()

    snapshot = get_system_snapshot()
    health = evaluate_health(snapshot, thresholds)

    payload = {**snapshot, "status": health["status"], "issues": health["issues"]}
    client.publish_status("system-health", payload)

    created_task_id = None
    if health["status"] == "critical":
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
            )
        else:
            print("[system_health_monitor] Brak default_admin_project — NIE tworzę zadania w Projectly.")

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
