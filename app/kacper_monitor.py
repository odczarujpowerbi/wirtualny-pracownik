"""
Kacper — monitor i samo-naprawa (rola z docs/przeplyw.html: "czyta wspólny
dziennik ~co 30s, sprawdza status wszystkich bieżących zadań i nietypowe
przebiegi... tworzy zadania naprawcze"). Status w dokumentacji: "brak" —
ten moduł to pierwsza wersja.

Czyta "wspólny dziennik" (state_store.events + job_scheduler.run_history) od
ostatniego przebiegu (kursor w runs/kacper_state.json, wzorzec z
task_feedback_requester.py) i wykrywa DWA wzorce, które żadne pojedyncze
zadanie nie ujawnia samo z siebie:

  1. praca cykliczna (job_scheduler, config/schedule.yaml) zawodzi
     powtarzalnie -> JEDNO zadanie naprawcze (deduplikowane per dzień).
     Żywy przykład, który uzasadnia ten mechanizm: 21.08.2026 runner_loop
     padał na KAŻDYM cyklu (uszkodzony runs/mock_comments.json) — scheduler
     łapie wyjątek i próbuje dalej, więc nikt by tego nie zauważył bez
     Kacpra czytającego historię przebiegów.
  2. ten sam skill/narzędzie (skill_usage_logger) zawodzi powtarzalnie w
     wielu zadaniach -> JEDNO zadanie naprawcze (deduplikowane per dzień).

Eskalacja POJEDYNCZEGO zadania (prompt injection, ryzyko czerwone, bramka po
wyczerpaniu pętli poprawek — patrz poprawka_materialu.py) dzieje się już
SYNCHRONICZNIE w runner_loop.py. Kacper tego nie duplikuje — widzi tylko
wzorce w agregacie.

Reszta (żadnego wzorca) trafia do statusu na żywo przez
client.publish_status("kacper-monitor", ...) — ten sam mechanizm co
system_health_monitor.py, osobna rola, nie nadpisuje statusu innych botów.

Bezargumentowa run_monitor_cycle() — dla job_scheduler.py (config/schedule.yaml,
job "kacper_monitor", domyślnie WYŁĄCZONY: tworzy zadania, jak inne joby z tą
adnotacją w schedule.default.yaml — włącz świadomie po przejrzeniu przebiegów).
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

import job_scheduler
import state_store
from projectly_client import get_client

STATE_PATH = Path(__file__).parent / "runs" / "kacper_state.json"
THRESHOLDS_PATH = Path(__file__).parent / "config" / "kacper_thresholds.yaml"


def load_thresholds(path=THRESHOLDS_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _load_state(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # Pierwsze włączenie: seedujemy od BIEŻĄCEGO max id, nie od 0 — inaczej
    # pierwszy przebieg skanuje retroaktywnie CAŁĄ historię zdarzeń (żywy
    # incydent 21.08.2026: pierwszy ręczny przebieg trafił w limit 2000
    # zdarzeń i założył zadanie naprawcze na podstawie starych, częściowo
    # już nieaktualnych niepowodzeń). Kacper ma monitorować od 'teraz'.
    return {"last_event_id": state_store.max_event_id(), "repair_tasks": {}}


def _save_state(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _skill_failures(events):
    """{skill_name: count} z eventów 'skill_usage:{skill}:failure' w partii."""
    counts = {}
    for ev in events:
        et = ev["event_type"] or ""
        if et.startswith("skill_usage:") and et.endswith(":failure"):
            skill = et.split(":", 2)[1]
            counts[skill] = counts.get(skill, 0) + 1
    return counts


def _job_health(thresholds):
    """{job_name: {failures, total, last_error}} liczone w OSTATNICH
    job_failure_window przebiegach KAŻDEGO joba (load_history: najnowszy pierwszy)."""
    window = thresholds.get("job_failure_window", 10)
    per_job = {}
    for record in job_scheduler.load_history(limit=500):
        bucket = per_job.setdefault(record["name"], [])
        if len(bucket) < window:
            bucket.append(record)

    health = {}
    for name, records in per_job.items():
        failures = [r for r in records if r["status"] != "ok"]
        if failures:
            health[name] = {
                "failures": len(failures),
                "total": len(records),
                "last_error": failures[0].get("error") or "brak szczegółu",
            }
    return health


def _today_key():
    return datetime.now(timezone.utc).date().isoformat()


def _create_repair_task(client, admin_project_id, title, description, assignee):
    """create_task w realnym Projectly wymaga project_id; zadania naprawcze
    Kacpra nie mają naturalnego (nie pochodzą z konkretnego projektu-zadania).
    Bez skonfigurowanego/rozpoznanego default_admin_project — fail-closed:
    NIE zgadujemy projektu, tylko logujemy lokalnie (widoczne w publish_status
    i wyjściu przebiegu), zamiast wywalić cały cykl monitorowania."""
    if not admin_project_id:
        print(f"[Kacper] Brak default_admin_project — NIE tworzę zadania w Projectly: {title}")
        return None
    return client.create_task(title, description, assigned_to=assignee, project_id=admin_project_id)


def run_monitor_cycle(client=None, thresholds=None, state_path=STATE_PATH):
    client = client or get_client()
    thresholds = thresholds or load_thresholds()
    state = _load_state(state_path)
    admin_project_id = client.default_admin_project_id()

    events = state_store.get_events_since(state.get("last_event_id", 0))
    new_last_id = events[-1]["id"] if events else state.get("last_event_id", 0)

    repair_created = []

    for job_name, info in _job_health(thresholds).items():
        if info["failures"] < thresholds.get("job_failure_threshold", 3):
            continue
        key = f"job:{job_name}:{_today_key()}"
        if key in state["repair_tasks"]:
            continue
        task_id = _create_repair_task(
            client, admin_project_id,
            f"Naprawa: zadanie cykliczne '{job_name}' zawodzi powtarzalnie",
            f"{info['failures']}/{info['total']} ostatnich przebiegów '{job_name}' "
            f"zakończyło się błędem.\nOstatni błąd: {info['last_error']}",
            thresholds.get("alert_assignee", "pawel"),
        )
        if task_id:
            state["repair_tasks"][key] = task_id
        repair_created.append({"kind": "job", "name": job_name, "task_id": task_id})

    for skill, count in _skill_failures(events).items():
        if count < thresholds.get("skill_failure_threshold", 3):
            continue
        key = f"skill:{skill}:{_today_key()}"
        if key in state["repair_tasks"]:
            continue
        task_id = _create_repair_task(
            client, admin_project_id,
            f"Naprawa: {skill} zawodzi powtarzalnie",
            f"{count} niepowodzeń '{skill}' w tej partii wspólnego dziennika.",
            thresholds.get("alert_assignee", "pawel"),
        )
        if task_id:
            state["repair_tasks"][key] = task_id
        repair_created.append({"kind": "skill", "name": skill, "task_id": task_id})

    state["last_event_id"] = new_last_id
    _save_state(state, state_path)

    summary = {"events_scanned": len(events), "repair_tasks_created": repair_created}
    client.publish_status("kacper-monitor", {**summary, "checked_at": datetime.now(timezone.utc).isoformat()})
    return summary


if __name__ == "__main__":
    print(run_monitor_cycle())
