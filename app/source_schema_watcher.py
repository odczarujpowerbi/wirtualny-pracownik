"""
Pilnuje struktury plików źródłowych (na start: CSV — Excel wymaga openpyxl,
celowo jeszcze nie dodany, patrz requirements.txt), wykrywa zmianę
kolumny/typu ZANIM odświeżenie się wywali, i sam tworzy zadanie dla
właściciela pliku zamiast czekać, aż ktoś odkryje awarię
(PLAN-WDROZENIA.md sekcja 10, SKRYPTY.md kategoria M — priorytet #2).

Bezpośrednia odpowiedź na największe potwierdzone znalezisko z analizy
godzin: ok. 214h firefightingu wokół "właściciel pliku zmienia strukturę
bez ostrzeżenia -> Power Query się wywala -> ręczne przepinanie".

Zasada z sekcji 12 planu ("Python przed AI"): to jest czysta, deterministyczna
detekcja różnicy struktury — zero wywołań modelu. AI wchodzi dopiero w
`pq_error_triage` (skill, SKRYPTY.md kategoria M), gdy trzeba zinterpretować
KONKRETNY wklejony błąd Power Query, nie samą zmianę struktury.
"""

import csv
import json
import re
from pathlib import Path

import yaml

from projectly_client import get_client

CONFIG_PATH = Path(__file__).parent / "config" / "watched_sources.yaml"
BASELINE_DIR = Path(__file__).parent / "runs" / "schema_baselines"


def _infer_type(value):
    if value is None or value == "":
        return None
    try:
        int(value)
        return "int"
    except ValueError:
        pass
    try:
        float(value.replace(",", "."))
        return "float"
    except ValueError:
        pass
    if re.match(r"^\d{4}-\d{2}-\d{2}", value):
        return "date"
    return "text"


def read_csv_schema(file_path, sample_rows=50):
    """Odczytuje nagłówek + próbkę wierszy, zwraca listę kolumn i
    dominujący typ każdej (heurystyka, nie certyfikowana walidacja typów —
    wystarczająca do wykrycia zmiany 'kolumna zniknęła/typ się zmienił')."""
    with open(file_path, encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        type_counts = {col: {} for col in header}
        row_count = 0
        for i, row in enumerate(reader):
            row_count += 1
            if i >= sample_rows:
                continue
            for col, val in zip(header, row):
                t = _infer_type(val)
                if t:
                    type_counts[col][t] = type_counts[col].get(t, 0) + 1

    types = {col: (max(counts, key=counts.get) if counts else "unknown") for col, counts in type_counts.items()}
    return {"columns": header, "types": types, "row_count": row_count}


def diff_schema(old_snapshot, new_snapshot):
    old_cols, new_cols = set(old_snapshot["columns"]), set(new_snapshot["columns"])
    added = sorted(new_cols - old_cols)
    removed = sorted(old_cols - new_cols)

    type_changes = {}
    for col in old_cols & new_cols:
        old_t, new_t = old_snapshot["types"].get(col), new_snapshot["types"].get(col)
        if old_t != new_t and "unknown" not in (old_t, new_t):
            type_changes[col] = {"before": old_t, "after": new_t}

    changed = bool(added or removed or type_changes)
    return {"changed": changed, "added_columns": added, "removed_columns": removed, "type_changes": type_changes}


def _describe_diff(diff):
    parts = []
    if diff["removed_columns"]:
        parts.append("zniknęły kolumny: " + ", ".join(diff["removed_columns"]))
    if diff["added_columns"]:
        parts.append("nowe kolumny: " + ", ".join(diff["added_columns"]))
    for col, change in diff["type_changes"].items():
        parts.append(f"zmiana typu '{col}': {change['before']} -> {change['after']}")
    return "; ".join(parts)


def _baseline_path(name):
    return BASELINE_DIR / f"{name}.json"


def check_source(name, file_path, owner, client=None):
    """Sprawdza jeden plik wobec ostatniej zapisanej struktury. Pierwsze
    uruchomienie dla danej nazwy tylko zapisuje bazową strukturę (nie ma
    z czym porównać). Po wykryciu zmiany baseline jest aktualizowany —
    kolejne uruchomienia porównują względem NOWEGO stanu, żeby nie tworzyć
    tego samego zadania w kółko."""
    current = read_csv_schema(file_path)
    baseline_file = _baseline_path(name)

    if not baseline_file.exists():
        baseline_file.parent.mkdir(parents=True, exist_ok=True)
        baseline_file.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"name": name, "status": "baseline_created"}

    baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
    diff = diff_schema(baseline, current)

    if not diff["changed"]:
        return {"name": name, "status": "unchanged"}

    client = client or get_client()
    task_id = client.create_task(
        title=f"Sprawdź zmianę struktury źródła: {name}",
        description=(
            f"Plik: {file_path}\nZmiana wykryta automatycznie: {_describe_diff(diff)}\n\n"
            "Prawdopodobny skutek: odświeżenie raportu może się wywalić albo policzyć "
            "błędne wartości. Potwierdź, czy zmiana jest zamierzona, zanim ktoś zbuduje "
            "na niej kolejny krok."
        ),
        assigned_to=owner,
    )
    baseline_file.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"name": name, "status": "changed", "diff": diff, "task_id": task_id}


def load_watched_sources(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("sources", [])


def check_all_watched_sources(config_path=CONFIG_PATH, client=None, base_dir=None):
    base_dir = base_dir or Path(__file__).parent
    client = client or get_client()
    results = []
    for source in load_watched_sources(config_path):
        file_path = base_dir / source["path"]
        results.append(check_source(source["name"], file_path, source["owner"], client=client))
    return results


if __name__ == "__main__":
    import shutil

    # Demo end-to-end: baseline na v1, potem podmiana na v2 (zmieniona
    # struktura) pod TĄ SAMĄ nazwą, żeby pokazać realną detekcję zmiany —
    # dokładnie scenariusz "właściciel pliku zmienił strukturę bez ostrzeżenia".
    demo_dir = Path(__file__).parent / "runs" / "_demo_source_watch"
    demo_dir.mkdir(parents=True, exist_ok=True)
    demo_file = demo_dir / "demo_source.csv"
    baseline_file = _baseline_path("demo_source")
    if baseline_file.exists():
        baseline_file.unlink()

    shutil.copy(Path(__file__).parent / "mock_data" / "source_sample_v1.csv", demo_file)
    print("1/2:", check_source("demo_source", demo_file, owner="asia"))

    shutil.copy(Path(__file__).parent / "mock_data" / "source_sample_v2_changed.csv", demo_file)
    print("2/2:", check_source("demo_source", demo_file, owner="asia"))
