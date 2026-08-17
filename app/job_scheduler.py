"""
Centralny scheduler dla WSZYSTKICH skryptów cyklicznych — jeden proces
zamiast osobnego wpisu w Harmonogramie zadań na każdy skrypt. Czyta
`config/schedule.yaml` (nazwa, moduł, funkcja, interwał, enabled) i
uruchamia każde zadanie we WŁASNYM wątku, gdy nadejdzie jego pora — bez
restartu procesu, jeśli zmienisz interwał w configu (odczytywany na nowo
co tick).

Odpowiedź na wprost zadane wymaganie: "program do monitoringu wszystkich
skryptów z możliwością zmiany ich harmonogramów... na nim opierałby się
monitoring całości mechanizmu". To JEST to centralne miejsce — stan
każdego zadania (ostatnie uruchomienie, czas trwania, sukces/błąd,
następne uruchomienie) trafia do `runs/scheduler_status.json`.

Dodanie NOWEGO przyszłego skryptu cyklicznego = jeden nowy wpis w
`config/schedule.yaml` (moduł musi mieć bezargumentową funkcję, np.
`run_once`/`run_health_check`) — bez zmiany kodu tego schedulera.

To JEDYNA rzecz, którą trzeba zarejestrować w Harmonogramie zadań Windows
przy starcie systemu — zastępuje 3 osobne wpisy z poprzedniego podejścia
(`runner_loop.py --loop`, `system_health_monitor.py --loop`,
`machine_status_reporter.py --loop`), które nadal działają samodzielnie,
jeśli ktoś woli klasyczne podejście — to nie jest jedyna droga, tylko
prostsza.

Sprawdza `kill_switch.py` na każdym ticku — aktywny kill switch wstrzymuje
odpalanie NOWYCH zadań (już trwające dokańczają się same).
"""

import importlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import kill_switch

SCHEDULE_PATH = Path(__file__).parent / "config" / "schedule.yaml"
STATUS_PATH = Path(__file__).parent / "runs" / "scheduler_status.json"

_state_lock = threading.Lock()

# PyYAML nie potrafi zachować komentarzy przy zapisie (yaml.safe_dump je
# gubi) — save_schedule() dopisuje więc ten nagłówek na nowo przy KAŻDYM
# zapisie (--set-interval/--enable/--disable), żeby dokumentacja configu
# nie znikała po pierwszej zmianie przez CLI.
SCHEDULE_HEADER = (
    "# Harmonogram wszystkich skryptów cyklicznych — czytany przez job_scheduler.py.\n"
    "# Edytuj wprost ALBO przez CLI (python job_scheduler.py --set-interval NAZWA SEKUNDY\n"
    "# / --enable NAZWA / --disable NAZWA) — scheduler w trybie ciągłym podchwyci\n"
    "# zmianę na najbliższym ticku, BEZ restartu procesu.\n"
    "#\n"
    "# Dodanie nowego przyszłego skryptu cyklicznego = nowy wpis tutaj (moduł musi\n"
    "# mieć bezargumentową funkcję, np. run_once/run_health_check) — bez zmiany\n"
    "# kodu job_scheduler.py.\n\n"
)


def load_schedule(path=SCHEDULE_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("jobs", [])


def save_schedule(jobs, path=SCHEDULE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(SCHEDULE_HEADER)
        yaml.safe_dump({"jobs": jobs}, f, allow_unicode=True, sort_keys=False)


def set_job_interval(name, interval_seconds, path=SCHEDULE_PATH):
    """Zmienia harmonogram JEDNEGO zadania bez ręcznej edycji YAML —
    scheduler w trybie ciągłym podchwyci zmianę na najbliższym ticku, bez
    restartu procesu."""
    jobs = load_schedule(path)
    if not any(j["name"] == name for j in jobs):
        raise ValueError(f"Brak zadania o nazwie '{name}' w {path}")
    for job in jobs:
        if job["name"] == name:
            job["interval_seconds"] = interval_seconds
    save_schedule(jobs, path)
    return jobs


def set_job_enabled(name, enabled, path=SCHEDULE_PATH):
    jobs = load_schedule(path)
    if not any(j["name"] == name for j in jobs):
        raise ValueError(f"Brak zadania o nazwie '{name}' w {path}")
    for job in jobs:
        if job["name"] == name:
            job["enabled"] = enabled
    save_schedule(jobs, path)
    return jobs


def _resolve_callable(job):
    module = importlib.import_module(job["module"])
    return getattr(module, job["function"])


def _load_state():
    if STATUS_PATH.exists():
        return json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    return {}


def _save_state(state):
    STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATUS_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_job(job, state):
    name = job["name"]
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()
    try:
        func = _resolve_callable(job)
        func()
        status, error = "ok", None
    except Exception as exc:  # noqa: BLE001 — jedno zawodne zadanie nie może ubić schedulera
        status, error = "error", str(exc)
    elapsed = round(time.monotonic() - t0, 1)

    with _state_lock:
        state[name] = {
            "last_run_at": started_at.isoformat(),
            "last_status": status,
            "last_error": error,
            "last_duration_seconds": elapsed,
            "next_run_at": (started_at + timedelta(seconds=job["interval_seconds"])).isoformat(),
        }
        _save_state(state)

    print(f"[{name}] {status} ({elapsed}s)" + (f" — {error}" if error else ""))


def run_scheduler(tick_seconds=5, schedule_path=SCHEDULE_PATH):
    state = _load_state()
    threads = {}

    print(f"job_scheduler.py wystartował — sprawdzanie harmonogramu co {tick_seconds}s (config: {schedule_path})")
    try:
        while True:
            if kill_switch.is_active():
                print(f"Kill switch aktywny ({kill_switch.reason()}) — nie odpalam nowych zadań.")
                time.sleep(tick_seconds)
                continue

            jobs = load_schedule(schedule_path)
            now = datetime.now(timezone.utc)

            for job in jobs:
                if not job.get("enabled", True):
                    continue
                name = job["name"]
                last = state.get(name)
                due = last is None or now >= datetime.fromisoformat(last["next_run_at"])
                already_running = name in threads and threads[name].is_alive()

                if due and not already_running:
                    t = threading.Thread(target=_run_job, args=(job, state), daemon=True)
                    threads[name] = t
                    t.start()

            time.sleep(tick_seconds)
    except KeyboardInterrupt:
        print("Zatrzymano ręcznie.")


def print_status(schedule_path=SCHEDULE_PATH):
    jobs = {j["name"]: j for j in load_schedule(schedule_path)}
    state = _load_state()
    print(f"{'Zadanie':<28}{'Interwał':>10}{'Wł.':>6}{'Ostatni status':>16}{'Trwał':>9}  Następny start")
    for name, job in jobs.items():
        s = state.get(name, {})
        duration = f"{s['last_duration_seconds']}s" if "last_duration_seconds" in s else "—"
        print(
            f"{name:<28}{str(job['interval_seconds']) + 's':>10}"
            f"{('tak' if job.get('enabled', True) else 'nie'):>6}"
            f"{s.get('last_status', '—'):>16}{duration:>9}  {s.get('next_run_at', '—')}"
        )


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true", help="Pokaż stan wszystkich zadań i zakończ")
    parser.add_argument("--set-interval", nargs=2, metavar=("NAZWA", "SEKUNDY"), help="Zmień interwał zadania")
    parser.add_argument("--enable", metavar="NAZWA")
    parser.add_argument("--disable", metavar="NAZWA")
    parser.add_argument("--tick", type=int, default=5, help="Co ile sekund sprawdzać harmonogram (domyślnie 5)")
    args = parser.parse_args()

    try:
        if args.status:
            print_status()
            return
        if args.set_interval:
            name, seconds = args.set_interval
            set_job_interval(name, int(seconds))
            print(f"Zmieniono interwał '{name}' na {seconds}s.")
            return
        if args.enable:
            set_job_enabled(args.enable, True)
            print(f"Włączono '{args.enable}'.")
            return
        if args.disable:
            set_job_enabled(args.disable, False)
            print(f"Wyłączono '{args.disable}'.")
            return
    except ValueError as exc:
        print(f"Błąd: {exc}")
        import sys

        sys.exit(1)

    run_scheduler(tick_seconds=args.tick)


if __name__ == "__main__":
    main()
