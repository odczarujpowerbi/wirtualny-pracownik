"""
Notatnik jako dodatkowa, lokalna ścieżka zadań — obok Projectly (PLAN-WDROZENIA.md
sekcja 11: intake z innych źródeł, każde źródło to osobny adapter wpięty w tę samą
pętlę). Wrzucasz linijkę do inbox/zadania.txt, a ten moduł przetwarza ją TYM SAMYM
pipeline'em co Projectly (runner_loop.process_task): klasyfikacja ryzyka, kontrola
prompt injection, realny worker, bramka, eskalacja, log decyzji do state.db.

Celowo domyślnie klient MOCK (get default) — to lokalna ścieżka do TESTOWANIA:
nic nie idzie do żywego Projectly, wynik i decyzje widać w dashboardzie
(zakładka "Przepływy agentów"). Realny klient tylko na jawne żądanie (--real).

Każde zadanie przetwarzane RAZ: dedup po skrócie treści linii, stan w
runs/notebook_processed.json. Notatnika NIE modyfikujemy (nieinwazyjnie) — żeby
powtórzyć zadanie, zmień treść linii albo skasuj plik stanu.

Użycie:
    python notebook_intake.py                 # jeden przebieg, klient mock
    python notebook_intake.py --inbox plik.txt --processed stan.json
    python notebook_intake.py --real           # użyj realnego Projectly (świadomie)
Wpięte też w scheduler (config/schedule.yaml, job `notebook_intake`).
"""

import argparse
import hashlib
import json
from pathlib import Path

import control
import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)
import kill_switch
import risk_classifier
import runner_loop
import task_router
from projectly_client import MockProjectlyClient, get_client

INBOX_PATH = Path(__file__).parent / "inbox" / "zadania.txt"
PROCESSED_PATH = Path(__file__).parent / "runs" / "notebook_processed.json"

RISK_TAGS = {"!green": "green", "!yellow": "yellow", "!red": "red"}


def parse_notebook(text):
    """Zamienia treść notatnika na listę zadań (pomija puste linie i komentarze #)."""
    return [_parse_line(line.strip()) for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")]


def _parse_line(raw):
    text = raw
    risk = "green"
    for tag, level in RISK_TAGS.items():
        if tag in text:
            risk, text = level, text.replace(tag, "")

    project_path = None
    url = None
    if "@" in text:
        text, _, target = text.partition("@")
        target = target.strip() or None
        # Po znaku @ może stać ścieżka PBIP albo adres www — rozstrzyga kształt
        # wartości, żeby notatnik pozostał jedną prostą składnią.
        if target and target.lower().startswith("https://"):
            url = target
        else:
            project_path = target

    title = " ".join(text.split())
    if not title and project_path:
        title = f"Waliduj strukturę PBIP {project_path}"
    if not title and url:
        title = f"Pobierz informacje ze źródła {url}"

    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    task = {
        "task_id": "NB-" + digest[:8],
        "title": title,
        "risk_level_hint": risk,
        "created_by": "notatnik",
        "source": "notebook",
        "_hash": digest,
    }
    if project_path:
        task["action"] = "validate_pbip"
        task["project_path"] = project_path
    if url:
        task["action"] = "fetch_url"
        task["url"] = url
    return task


def append_task(title, risk="green", project_path=None, inbox_path=INBOX_PATH):
    """Dopisuje jedno zadanie do notatnika w formacie, który rozumie parser
    (używane przez formularz 'Dodaj zadanie' w dashboardzie). Zwraca dopisaną linię."""
    title = (title or "").strip()
    if not title:
        raise ValueError("Zadanie musi mieć treść.")
    line = title
    if project_path and project_path.strip():
        line += f" @ {project_path.strip()}"
    if risk in ("yellow", "red"):
        line += f" !{risk}"

    inbox_path = Path(inbox_path)
    inbox_path.parent.mkdir(parents=True, exist_ok=True)
    with open(inbox_path, "a", encoding="utf-8") as f:
        f.write(line + "\n")
    return line


def _load_processed(path):
    if Path(path).exists():
        return set(json.loads(Path(path).read_text(encoding="utf-8")))
    return set()


def _save_processed(processed, path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(sorted(processed), ensure_ascii=False, indent=2), encoding="utf-8")


def run_once(client=None, inbox_path=INBOX_PATH, processed_path=PROCESSED_PATH):
    """Jeden przebieg intake'u notatnika: czyta plik, przetwarza NOWE zadania."""
    if kill_switch.is_active():
        print(f"Kill switch aktywny ({kill_switch.reason()}) — notebook intake nie podejmuje akcji.")
        return {"processed": 0, "reason": "kill_switch"}
    if control.is_paused():
        print(f"PAUSE ({control.pause_reason()}) — notebook intake nie podejmuje nowej pracy.")
        return {"processed": 0, "reason": "paused"}

    inbox_path = Path(inbox_path)
    if not inbox_path.exists():
        return {"processed": 0, "reason": "brak pliku notatnika"}

    client = client or MockProjectlyClient()
    policy = risk_classifier.load_policy()
    routing = task_router.load_routing()
    processed = _load_processed(processed_path)

    seen = set()
    new_tasks = []
    for task in parse_notebook(inbox_path.read_text(encoding="utf-8")):
        h = task["_hash"]
        if h in processed or h in seen:
            continue
        seen.add(h)
        new_tasks.append(task)

    results = []
    for task in new_tasks:
        h = task.pop("_hash")  # pełny skrót zapamiętany przed usunięciem z payloadu
        results.append(runner_loop.process_task(task, policy, routing, client))
        processed.add(h)

    if results:
        _save_processed(processed, processed_path)
    print(f"Notebook intake: przetworzono {len(results)} nowych zadań z {inbox_path.name}.")
    return {"processed": len(results), "results": results}


def main():
    parser = argparse.ArgumentParser(description="Intake zadań z notatnika (lokalna ścieżka obok Projectly).")
    parser.add_argument("--inbox", default=str(INBOX_PATH), help="Ścieżka pliku notatnika")
    parser.add_argument("--processed", default=str(PROCESSED_PATH), help="Plik stanu (dedup przetworzonych)")
    parser.add_argument("--real", action="store_true", help="Użyj realnego Projectly zamiast mocka (świadomie)")
    args = parser.parse_args()

    client = get_client() if args.real else MockProjectlyClient()
    result = run_once(client=client, inbox_path=args.inbox, processed_path=args.processed)
    for r in result.get("results", []):
        print(r)


if __name__ == "__main__":
    main()
