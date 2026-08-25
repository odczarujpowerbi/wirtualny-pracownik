"""
Cykliczny (domyślnie co godzinę) raport statusu MASZYNY do Projectly:
jakie narzędzia są zainstalowane i w jakiej wersji (git/Python/Claude
Code), jak poszedł ostatni bootstrap (`bootstrap_all.py`/`.ps1` — czyta
`runs/bootstrap_history.json`), plus bieżący stan RAM (reużywa
`system_health_monitor.get_system_snapshot()`, żeby nie duplikować tej
logiki).

UCZCIWA GRANICA: wysyłka idzie przez TEN SAM interfejs co
`live_status_publisher.py` i `system_health_monitor.py` —
`client.publish_status()`. Dedykowana funkcja MCP (`post_agent_status`) jest
już podłączona w `ProjectlyClient.publish_status` (`projectly_client.py`,
config `live_status.transport: agent_status_tool`) — TEN skrypt nie wymaga
ŻADNEJ zmiany niezależnie od transportu, bo woła dokładnie ten sam interfejs
co zawsze; payload (kształt inny niż `live_status_publisher.py`) jest
normalizowany centralnie w `_map_status_payload` (`projectly_client.py`).

Różnica względem `system_health_monitor.py` (co 2 min, eskaluje zadanie
przy problemie): to jest rzadszy, czysto informacyjny zapis stanu —
audyt/historia, nie alarm. Uzupełniają się, nie duplikują.
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import system_health_monitor
from projectly_client import get_client

BOOTSTRAP_HISTORY_PATH = Path(__file__).parent / "runs" / "bootstrap_history.json"


def _tool_version(command, args=("--version",)):
    try:
        result = subprocess.run([command, *args], capture_output=True, text=True, timeout=5)
        return (result.stdout.strip() or result.stderr.strip()) or None
    except (FileNotFoundError, OSError):
        return None
    except subprocess.TimeoutExpired:
        return None


def get_tool_versions():
    return {
        "git": _tool_version("git"),
        "python": _tool_version("python") or _tool_version("python3"),
        "claude_code": _tool_version("claude"),
    }


def load_bootstrap_history(path=BOOTSTRAP_HISTORY_PATH):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def build_machine_status():
    import live_status_publisher

    snapshot = system_health_monitor.get_system_snapshot()
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tool_versions": get_tool_versions(),
        "last_bootstrap": load_bootstrap_history(),
        "ram_available_percent": snapshot["ram_available_percent"],
        "running_scripts": snapshot["running_scripts"],
        "update_interval_seconds": live_status_publisher._skonfigurowany_interwal(
            "machine_status_reporter", 3600),
    }


def run_machine_status_report(client=None):
    client = client or get_client()
    status = build_machine_status()
    client.publish_status("machine-status", status)
    return status


def main():
    import argparse
    import time

    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Ciągła pętla zamiast jednego przebiegu")
    parser.add_argument("--interval", type=int, default=3600, help="Sekundy między przebiegami (domyślnie 3600 = 1h)")
    args = parser.parse_args()

    if not args.loop:
        print(run_machine_status_report())
        return

    print(f"Raport statusu maszyny w trybie ciągłym, interwał {args.interval}s. Ctrl+C żeby zatrzymać.")
    try:
        while True:
            print(run_machine_status_report())
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("Zatrzymano ręcznie.")


if __name__ == "__main__":
    main()
