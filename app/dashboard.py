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

    GET  /              -> strona dashboard.html
    GET  /api/state     -> zadania + status + historia przebiegów (JSON)
    POST /api/schedule  -> zmiana interwału / włączenia / opisu jednego zadania
    POST /api/run       -> uruchom jedno zadanie natychmiast (poza harmonogramem)

Serwer słucha TYLKO na 127.0.0.1 (localhost) — nie jest wystawiony na sieć.
'Uruchom teraz' odpala wyłącznie zadania zadeklarowane w schedule.yaml,
nigdy dowolny kod.
"""

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import job_scheduler

HOST = "127.0.0.1"
PORT = 8787
HTML_PATH = Path(__file__).parent / "dashboard.html"


def build_state():
    return {
        "jobs": job_scheduler.load_schedule(),
        "status": job_scheduler._load_state(),
        "history": job_scheduler.load_history(limit=100),
    }


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
