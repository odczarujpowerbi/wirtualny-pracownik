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

import contextlib
import importlib
import io
import json
import threading
import time
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

import control
import env_bootstrap  # noqa: F401 — wymusza UTF-8 na stdout/stderr dla procesu schedulera (autostart Windows)
import kill_switch
import scheduler_lock

# Ile znakow wyjscia (stdout+stderr) zapisujemy na przebieg. Powyzej tego
# obcinamy, zeby pojedynczy zapyziaczony przebieg nie rozdal pliku historii.
MAX_OUTPUT_CHARS = 200_000

# WATCHDOG (żywy incydent 25.08.2026): runner_loop/notebook_intake/kacper_monitor/
# system_health_monitor zawiesiły się na 2+ godziny na "ciekącym" połączeniu
# sieciowym (naprawione osobno w mcp_client.py, patrz total timeout w _rpc) —
# ale to jest DRUGA linia obrony na wypadek JAKIEJKOLWIEK innej przyszłej
# przyczyny zawieszenia wątku (deadlock, inny hang sieciowy, cokolwiek).
# `already_running` (nazwa_joba -> wątek wciąż `is_alive()`) normalnie blokuje
# start nowego przebiegu, dopóki poprzedni nie skończy — bez limitu, zawieszony
# wątek blokuje TEN JOB na zawsze. Domyślny limit jest generous (30 min) —
# indywidualny job może go podwyższyć w schedule.yaml (`max_duration_seconds`),
# jeśli legalnie potrzebuje więcej (np. runner_loop przy wielu zadaniach
# agentic_worker, patrz agentic_worker.AGENTIC_TIMEOUT_SECONDS).
DEFAULT_MAX_DURATION_SECONDS = 1800


def _watchdog_timeout_exceeded(started_at, now, limit_seconds):
    """Wyodrębnione z run_scheduler() dla testowalności bez realnej pętli/blokady
    plikowej. True = wątek żyje dłużej niż limit, traktujemy go jako zawieszony."""
    return started_at is not None and (now - started_at).total_seconds() > limit_seconds

SCHEDULE_PATH = Path(__file__).parent / "config" / "schedule.yaml"
# Szablon SLEDZONY w gicie. schedule.yaml (LIVE) jest poza gitem (.gitignore),
# bo aplikacja go zapisuje w runtime (dashboard/CLI) - gdyby byl sledzony,
# kazdy git pull konfliktowalby. Rozdzial: SZABLON w repo, LIVE lokalnie.
DEFAULT_SCHEDULE_PATH = Path(__file__).parent / "config" / "schedule.default.yaml"
STATUS_PATH = Path(__file__).parent / "runs" / "scheduler_status.json"
HISTORY_PATH = Path(__file__).parent / "runs" / "run_history.jsonl"

# scheduler_status.json trzyma tylko OSTATNI przebieg każdego zadania.
# run_history.jsonl to dziennik dopisywany co przebieg (jeden JSON na linię),
# żeby dashboard mógł pokazać "co się działo", nie tylko "co jest teraz".
# Plik przycinamy do MAX_HISTORY ostatnich wpisów, żeby nie rósł bez końca.
MAX_HISTORY = 1000

_state_lock = threading.Lock()
_history_writes = 0

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


def _read_jobs(path):
    """Surowy odczyt listy jobow z pliku YAML (bez seedowania) — unika rekurencji."""
    with open(path, encoding="utf-8") as f:
        return (yaml.safe_load(f) or {}).get("jobs", [])


def _ensure_live_schedule():
    """Utrzymuje LIVE schedule.yaml zsynchronizowany z SZABLONEM, bez kasowania
    lokalnych przelacznikow: (1) brak live -> kopiuj z szablonu; (2) live istnieje
    -> domeruj joby z szablonu, ktorych nie ma lokalnie (po nazwie). Lokalne
    zmiany enabled/interval istniejacych jobow zostaja nietkniete."""
    if not DEFAULT_SCHEDULE_PATH.exists():
        return  # brak szablonu (np. bardzo stary checkout) — nic nie robimy
    if not SCHEDULE_PATH.exists():
        save_schedule(_read_jobs(DEFAULT_SCHEDULE_PATH), SCHEDULE_PATH)
        return
    live = _read_jobs(SCHEDULE_PATH)
    live_names = {j["name"] for j in live}
    new_jobs = [j for j in _read_jobs(DEFAULT_SCHEDULE_PATH) if j["name"] not in live_names]
    if new_jobs:
        live.extend(new_jobs)
        save_schedule(live, SCHEDULE_PATH)


def load_schedule(path=SCHEDULE_PATH):
    # Tylko dla realnej sciezki LIVE seedujemy/domergowujemy z szablonu. Dla
    # jawnie podanej innej sciezki (testy z plikiem tymczasowym) — czysty odczyt.
    if Path(path) == SCHEDULE_PATH:
        _ensure_live_schedule()
    return _read_jobs(path)


def save_schedule(jobs, path=SCHEDULE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(SCHEDULE_HEADER)
        yaml.safe_dump({"jobs": jobs}, f, allow_unicode=True, sort_keys=False)


def update_job(name, updates, path=SCHEDULE_PATH):
    """Zmienia wybrane pola JEDNEGO zadania bez ręcznej edycji YAML —
    scheduler w trybie ciągłym podchwyci zmianę na najbliższym ticku, bez
    restartu procesu. `updates` to słownik pól do nadpisania, np.
    {"interval_seconds": 60, "enabled": False, "description": "..."}."""
    jobs = load_schedule(path)
    if not any(j["name"] == name for j in jobs):
        raise ValueError(f"Brak zadania o nazwie '{name}' w {path}")
    for job in jobs:
        if job["name"] == name:
            job.update(updates)
    save_schedule(jobs, path)
    return jobs


def set_job_interval(name, interval_seconds, path=SCHEDULE_PATH):
    return update_job(name, {"interval_seconds": interval_seconds}, path)


def set_job_enabled(name, enabled, path=SCHEDULE_PATH):
    return update_job(name, {"enabled": enabled}, path)


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


def _append_history(record):
    global _history_writes
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    _history_writes += 1
    if _history_writes % 200 == 0:
        _trim_history()


def _trim_history(keep=MAX_HISTORY):
    if not HISTORY_PATH.exists():
        return
    lines = [ln for ln in HISTORY_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) > keep:
        HISTORY_PATH.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")


def load_history(limit=100, include_output=False):
    """Ostatnie `limit` przebiegów, najnowszy pierwszy — do listy w dashboardzie.
    Domyślnie BEZ pola `output` (pełne wyjście bywa duże) — do szczegółu
    pojedynczego przebiegu służy `get_run_log(run_id)`."""
    if not HISTORY_PATH.exists():
        return []
    lines = [ln for ln in HISTORY_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
    records = list(reversed([json.loads(ln) for ln in lines[-limit:]]))
    if not include_output:
        for record in records:
            record.pop("output", None)
    return records


def get_run_log(run_id):
    """Pełny zapis JEDNEGO przebiegu (z wyjściem `output`) po jego id —
    do widoku szczegółu po kliknięciu w przebieg. None, gdy nie ma."""
    if not HISTORY_PATH.exists():
        return None
    lines = HISTORY_PATH.read_text(encoding="utf-8").splitlines()
    for line in reversed(lines):
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("id") == run_id:
            return record
    return None


def _summarize_result(returned):
    """Krótkie, czytelne streszczenie wartości zwróconej przez zadanie —
    do kolumny/nagłówka szczegółu. Pełne wyjście i tak jest w `output`."""
    if returned is None:
        return None
    try:
        text = json.dumps(returned, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = repr(returned)
    return text if len(text) <= 2000 else text[:2000] + " …(obcięto)"


def _run_job(job, state, trigger="schedule"):
    name = job["name"]
    run_id = uuid.uuid4().hex[:12]
    started_at = datetime.now(timezone.utc)
    t0 = time.monotonic()

    # Przechwytujemy wszystko, co zadanie wypisze (stdout+stderr) ORAZ wartość,
    # którą zwróci — to jest dokładnie ten "pełny status", który chcemy móc
    # obejrzeć klikając w przebieg. Bez tego wyjście skryptów donikąd nie szło.
    buffer = io.StringIO()
    result_summary = None
    try:
        func = _resolve_callable(job)
        with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
            returned = func()
        result_summary = _summarize_result(returned)
        status, error = "ok", None
    except Exception as exc:  # noqa: BLE001 — jedno zawodne zadanie nie może ubić schedulera
        status, error = "error", str(exc)
        buffer.write("\n" + traceback.format_exc())
    elapsed = round(time.monotonic() - t0, 1)

    output = buffer.getvalue()
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n…(wyjście obcięte)"

    with _state_lock:
        state[name] = {
            "last_run_at": started_at.isoformat(),
            "last_status": status,
            "last_error": error,
            "last_duration_seconds": elapsed,
            "last_run_id": run_id,
            "next_run_at": (started_at + timedelta(seconds=job["interval_seconds"])).isoformat(),
        }
        _save_state(state)
        _append_history({
            "id": run_id,
            "name": name,
            "run_at": started_at.isoformat(),
            "status": status,
            "error": error,
            "duration_seconds": elapsed,
            "trigger": trigger,
            "result": result_summary,
            "output": output,
        })

    print(f"[{name}] {status} ({elapsed}s)" + (f" — {error}" if error else ""))


def run_job_by_name(name, path=SCHEDULE_PATH):
    """Odpala JEDNO zadanie natychmiast, poza harmonogramem (przycisk
    'uruchom teraz' w dashboardzie). Uruchamia tylko zadania zadeklarowane
    w schedule.yaml — nigdy dowolny kod. Wynik trafia do statusu i historii
    tak samo jak przebieg z harmonogramu."""
    jobs = load_schedule(path)
    job = next((j for j in jobs if j["name"] == name), None)
    if job is None:
        raise ValueError(f"Brak zadania o nazwie '{name}' w {path}")
    state = _load_state()
    _run_job(job, state, trigger="manual")
    return state.get(name)


def run_scheduler(tick_seconds=5, schedule_path=SCHEDULE_PATH):
    lock = scheduler_lock.acquire()
    if not lock["ok"]:
        print(lock["detail"])
        import sys

        sys.exit(1)

    state = _load_state()
    threads = {}
    thread_started_at = {}

    print(f"job_scheduler.py wystartował — sprawdzanie harmonogramu co {tick_seconds}s (config: {schedule_path})")
    try:
        while True:
            if kill_switch.is_active():
                print(f"Kill switch aktywny ({kill_switch.reason()}) — nie odpalam nowych zadań.")
                time.sleep(tick_seconds)
                continue
            if control.is_paused():
                print(f"PAUSE ({control.pause_reason()}) — nie odpalam nowych zadań.")
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
                wątek = threads.get(name)
                already_running = wątek is not None and wątek.is_alive()

                if already_running:
                    started = thread_started_at.get(name)
                    limit = job.get("max_duration_seconds", DEFAULT_MAX_DURATION_SECONDS)
                    if _watchdog_timeout_exceeded(started, now, limit):
                        print(f"[{name}] WATCHDOG: wątek żyje {(now - started).total_seconds():.0f}s "
                              f"(limit {limit}s) — traktuję jako zawieszony, odpalam nowy przebieg "
                              "(stary wątek zostaje osierocony, daemon — nie blokuje procesu).")
                        already_running = False

                if due and not already_running:
                    t = threading.Thread(target=_run_job, args=(job, state), daemon=True)
                    threads[name] = t
                    thread_started_at[name] = now
                    t.start()

            time.sleep(tick_seconds)
    except KeyboardInterrupt:
        print("Zatrzymano ręcznie.")
    finally:
        scheduler_lock.release()


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
