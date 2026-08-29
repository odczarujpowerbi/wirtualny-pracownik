"""
Dashboard schedulera — jedno okno (strona w przeglądarce), z którego widać
KAŻDY przebieg każdego skryptu i z którego edytujesz harmonogramy bez
dotykania YAML-a ani terminala.

Uruchomienie:
    python dashboard.py
otwiera http://127.0.0.1:8787/ w domyślnej przeglądarce.

To celowo mały serwer na bibliotece standardowej Pythona (http.server) —
zero nowych zależności. Cała logika harmonogramu i historii siedzi w
job_scheduler.py; ten plik to tylko cienka warstwa HTTP nad nim:

    GET  /                    -> strona dashboard.html
    GET  /api/state           -> zadania + status + historia przebiegów (JSON)
    POST /api/schedule        -> zmiana interwału / włączenia / opisu jednego zadania
    POST /api/run             -> uruchom jedno zadanie natychmiast (poza harmonogramem)
    GET  /api/agents          -> status (działa/nie) każdego bota (dev/checker/marketing/zarząd)
    POST /api/agents/start    -> odpala PROCES joba wskazanej roli (jeśli nie działa)
    POST /api/agents/start-all -> to samo dla wszystkich ról naraz

Serwer słucha TYLKO na 127.0.0.1 (localhost) — nie jest wystawiony na sieć.
'Uruchom teraz' odpala wyłącznie zadania zadeklarowane w schedule.yaml,
nigdy dowolny kod. 'Uruchom agenta' (dodane 29.08.2026, do testowania)
odpala WYŁĄCZNIE jeden ze znanych .bat-ów (AGENT_BAT_FILES), nigdy
dowolną ścieżkę z requestu.
"""

import json
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import control
import job_scheduler
import kill_switch
import live_status_publisher
import notebook_intake
import scheduler_lock
import state_store
import usage_monitor

HOST = "127.0.0.1"
PORT = 8787
HTML_PATH = Path(__file__).parent / "dashboard.html"

# Przyciski "uruchom agenta X" (dodane 29.08.2026, na wyraźną prośbę
# właściciela — do testowania: chce móc odpalić każdego bota osobno, bez
# grzebania w Harmonogramie zadań Windows/terminalu). Repo root = katalog
# NADRZĘDNY wobec app/ (ten plik jest w app/, .bat-y w korzeniu repo). "dev"
# przemianowany z "start-agent.bat" na "start-agent-dev.bat" 29.08.2026 (spójność
# nazw z checker/marketing/zarząd). "zarzad" (29.08.2026) — czwarta, niezależna
# rola (konto "AI - Zarząd" w Projectly, wcześniej odbierane przy okazji przez
# proces dev — patrz config/projectly.yaml poll.extra_accounts).
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
    zamknięcie tego dashboardu/przeglądarki i nie otwiera widocznego okna
    konsoli — ma działać w tle jak uruchomiony przez Harmonogram zadań."""
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW
    subprocess.Popen(cmd, cwd=str(cwd), **kwargs)


def build_agents():
    """Status (działa/nie działa) każdego bota na tej maszynie —
    do panelu 'Agenci' w dashboardzie. is_running() to prawdziwy test
    żywotności procesu (scheduler_lock.py), nie tylko obecność pliku."""
    return {"agents": [{"role": rola, "running": scheduler_lock.is_running(rola)}
                       for rola in AGENT_BAT_FILES]}


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


def start_all_agents():
    return {"results": {rola: start_agent(rola) for rola in AGENT_BAT_FILES}}


def build_state():
    """Zagregowany widok WSZYSTKICH ról (dev/checker/marketing/zarząd, patrz
    job_scheduler.discover_roles()) — dodane 29.08.2026, kiedy stan/historia
    stały się plikami PER ROLA (job_scheduler._status_path_for_role itd.).
    Bez tej agregacji dashboard pokazywałby tylko rolę procesu, pod którym
    sam akurat działa — operator otwierający `python dashboard.py` chce widzieć
    WSZYSTKICH botów na tej maszynie naraz, nie tylko jednego."""
    jobs = job_scheduler.load_schedule()
    status, history = {}, []
    for rola in job_scheduler.discover_roles():
        # Dla WŁASNEJ roli procesu (job_scheduler.CURRENT_ROLE) czytamy globalne
        # STATUS_PATH/HISTORY_PATH (nie świeżo przeliczoną ścieżkę) — to jedyne
        # miejsce, które testy/ewentualne nadpisanie na żywo mogą podmienić;
        # dla POZOSTAŁYCH ról nie ma czego podmieniać, liczymy wprost z nazwy roli.
        if rola == job_scheduler.CURRENT_ROLE:
            status_path, history_path = job_scheduler.STATUS_PATH, job_scheduler.HISTORY_PATH
        else:
            status_path = job_scheduler._status_path_for_role(rola)
            history_path = job_scheduler._history_path_for_role(rola)
        stan_roli = job_scheduler._load_state(status_path)
        for nazwa, info in stan_roli.items():
            status[nazwa] = {**info, "role": rola}
        for rekord in job_scheduler.load_history(limit=100, path=history_path):
            history.append({**rekord, "role": rola})
    history.sort(key=lambda r: r.get("run_at") or "", reverse=True)
    return {
        "jobs": jobs,
        "status": status,
        "history": history[:100],
    }


def build_flows(limit=200):
    """Zakładka 'Przepływy' (M2b): ostatnie decyzje agentów z state.db —
    kto → co → dlaczego → model → koszt. Źródło do podglądu na żywo i analizy."""
    return {"decisions": state_store.get_recent_decisions(limit=limit)}


def build_tasks(limit=40):
    """Główny widok 'Zadania': zadania pogrupowane z osią czasu kroków, decyzji
    i statusów poszczególnych agentów."""
    return {"tasks": state_store.get_tasks_with_timeline(limit=limit)}


def _process_notebook_safely():
    try:
        notebook_intake.run_once()
    except Exception as exc:  # noqa: BLE001 — wątek w tle: błąd logujemy, nie wywracamy serwera
        print(f"[dashboard] błąd przetwarzania notatnika: {exc}")


def build_health():
    """Pasek kondycji panelu operatora: stan sterowania (running/paused/stopped) +
    metryki na żywo (kolejka, koszt, zdrowie, heartbeat) z live_status_publisher."""
    status = live_status_publisher.build_status(role="dev")
    status["control"] = control.state()
    status["pause_reason"] = control.pause_reason()
    status["stop_reason"] = kill_switch.reason() or ""
    # Zuzycie Claude (limity okna 5h/dzis) + estymacja ile zadan jeszcze.
    try:
        status["usage"] = usage_monitor.summary()
    except Exception as exc:  # noqa: BLE001 - monitor zuzycia nie moze wywrocic health
        status["usage"] = {"available": False, "reason": str(exc)}
    return status


def _validate_updates(body):
    """Whitelist pól, które wolno zmienić z UI — reszta jest ignorowana."""
    updates = {}
    if "interval_seconds" in body:
        interval = int(body["interval_seconds"])
        if interval <= 0:
            raise ValueError("Interwał musi być dodatnią liczbą sekund.")
        updates["interval_seconds"] = interval
    if "enabled" in body:
        updates["enabled"] = bool(body["enabled"])
    if "description" in body:
        updates["description"] = str(body["description"]).strip()
    if not updates:
        raise ValueError("Brak pól do zmiany.")
    return updates


def _run_safely(name):
    try:
        job_scheduler.run_job_by_name(name)
    except Exception as exc:  # noqa: BLE001 — wątek w tle: błąd logujemy, nie wywracamy serwera
        print(f"[dashboard] błąd ręcznego uruchomienia '{name}': {exc}")


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # cichy serwer — bez zaśmiecania konsoli logami HTTP
        pass

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ("/", "/index.html"):
            self._serve_html()
        elif parsed.path == "/api/state":
            self._send_json(build_state())
        elif parsed.path == "/api/flows":
            self._send_json(build_flows())
        elif parsed.path == "/api/tasks":
            self._send_json(build_tasks())
        elif parsed.path == "/api/health":
            self._send_json(build_health())
        elif parsed.path == "/api/agents":
            self._send_json(build_agents())
        elif parsed.path == "/api/run-log":
            self._handle_run_log(parse_qs(parsed.query))
        else:
            self._send_error("not_found", "Nieznana ścieżka.", status=404)

    def _handle_run_log(self, query):
        run_id = (query.get("id") or [""])[0]
        if not run_id:
            self._send_error("bad_request", "Brak parametru 'id'.", status=400)
            return
        record = job_scheduler.get_run_log(run_id)
        if record is None:
            self._send_error("not_found", "Nie ma przebiegu o tym id.", status=404)
            return
        self._send_json({"data": record})

    def do_POST(self):
        try:
            if self.path == "/api/schedule":
                self._handle_schedule()
            elif self.path == "/api/run":
                self._handle_run()
            elif self.path == "/api/add-task":
                self._handle_add_task()
            elif self.path == "/api/control":
                self._handle_control()
            elif self.path == "/api/agents/start":
                self._handle_agent_start()
            elif self.path == "/api/agents/start-all":
                self._send_json({"data": start_all_agents()})
            else:
                self._send_error("not_found", "Nieznana ścieżka.", status=404)
        except ValueError as exc:
            self._send_error("bad_request", str(exc), status=400)

    def _handle_schedule(self):
        body = self._read_json_body()
        name = body.get("name")
        if not name:
            raise ValueError("Brak pola 'name'.")
        job_scheduler.update_job(name, _validate_updates(body))
        self._send_json({"data": build_state()})

    def _handle_run(self):
        body = self._read_json_body()
        name = body.get("name")
        if not name:
            raise ValueError("Brak pola 'name'.")
        if not any(j["name"] == name for j in job_scheduler.load_schedule()):
            raise ValueError(f"Brak zadania '{name}' w harmonogramie.")
        threading.Thread(target=_run_safely, args=(name,), daemon=True).start()
        self._send_json({"data": {"message": f"Uruchomiono '{name}' w tle."}}, status=202)

    def _handle_agent_start(self):
        body = self._read_json_body()
        role = body.get("role")
        if not role:
            raise ValueError("Brak pola 'role'.")
        self._send_json({"data": start_agent(role)})

    def _handle_add_task(self):
        """Dopisuje zadanie do notatnika (inbox/zadania.txt) i od razu je przetwarza
        w tle klientem mock — nie czekając na 60-sekundowy tick schedulera."""
        body = self._read_json_body()
        title = (body.get("title") or "").strip()
        risk = body.get("risk", "green")
        project_path = (body.get("project_path") or "").strip() or None
        if not title:
            raise ValueError("Brak treści zadania.")
        if risk not in ("green", "yellow", "red"):
            raise ValueError("Nieznany poziom ryzyka (dozwolone: green/yellow/red).")

        line = notebook_intake.append_task(title, risk=risk, project_path=project_path)
        threading.Thread(target=_process_notebook_safely, daemon=True).start()
        self._send_json({"data": {"message": f"Dodano i przetwarzam: {line}"}}, status=202)

    def _handle_control(self):
        """Panel operatora: pause / resume / stop / start (M3, OPS-01)."""
        body = self._read_json_body()
        new_state, message = control.apply(body.get("action"))
        self._send_json({"data": {"state": new_state, "message": message}})

    def _serve_html(self):
        body = HTML_PATH.read_bytes()
        self._send_bytes(body, "text/html; charset=utf-8")

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(body, "application/json; charset=utf-8", status=status)

    def _send_error(self, code, message, status):
        self._send_json({"error": {"code": code, "message": message}}, status=status)

    def _send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))


def main():
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    url = f"http://{HOST}:{PORT}/"
    print(f"Dashboard działa: {url}  (Ctrl+C żeby zatrzymać)")
    try:
        webbrowser.open(url)
    except Exception:  # noqa: BLE001 — brak przeglądarki nie może wywalić serwera
        pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZatrzymano dashboard.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
