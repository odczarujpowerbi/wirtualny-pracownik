"""
Waliduje strukturę projektu PBIP (PBI-01, PLAN-WDROZENIA.md sekcja 10,
SKRYPTY.md kategoria E). PBIP to zwykłe pliki tekstowe/JSON/TMDL, więc
warstwę strukturalną da się sprawdzić bez Power BI Desktop w ogóle.

Czego ten moduł NIE robi (uczciwie, nie udaje): nie otwiera raportu w
Power BI Desktop, nie robi zrzutów ekranu stron (to wymaga Desktop Bridge
na prawdziwej maszynie Windows — SKRYPTY.md `pbip_screenshot_all_pages.py`).
Sprawdza tylko to, co da się sprawdzić z samych plików: strukturę projektu,
poprawność JSON, obecność plików modelu.
"""

import json
from pathlib import Path


def validate_pbip(project_dir):
    """project_dir: folder zawierający plik .pbip. Zwraca listę problemów
    (pusta lista = struktura poprawna) i listę ostrzeżeń."""
    project_dir = Path(project_dir)
    errors = []
    warnings = []

    pbip_files = list(project_dir.glob("*.pbip"))
    if not pbip_files:
        return {"errors": ["Brak pliku .pbip w podanym folderze."], "warnings": []}

    pbip_path = pbip_files[0]
    try:
        pbip_data = json.loads(pbip_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return {"errors": [f"Plik .pbip nie jest poprawnym JSON: {e}"], "warnings": []}

    if "version" not in pbip_data:
        warnings.append("Plik .pbip nie ma pola 'version' — sprawdź zgodność z aktualnym formatem.")

    artifacts = pbip_data.get("artifacts", [])
    if not artifacts:
        errors.append("Plik .pbip nie deklaruje żadnych artefaktów (report/semantic model).")

    validated_report_folders = set()
    for artifact in artifacts:
        report_ref = artifact.get("report", {}).get("path")
        if report_ref:
            folder = (project_dir / report_ref).resolve()
            validated_report_folders.add(folder)
            errors.extend(_validate_report_folder(folder))

    for folder in project_dir.glob("*.Report"):
        if folder.resolve() not in validated_report_folders:
            errors.extend(_validate_report_folder(folder))

    model_folders = list(project_dir.glob("*.SemanticModel"))
    if not model_folders:
        warnings.append("Brak folderu *.SemanticModel — projekt może być tylko raportem bez własnego modelu.")
    for folder in model_folders:
        errors.extend(_validate_semantic_model_folder(folder))

    # Deduplikacja z zachowaniem kolejności — na wypadek innych nakładających się ścieżek.
    errors = list(dict.fromkeys(errors))
    warnings = list(dict.fromkeys(warnings))

    return {"errors": errors, "warnings": warnings}


def _validate_report_folder(folder):
    errors = []
    folder = Path(folder)
    if not folder.exists():
        return [f"Folder raportu {folder} nie istnieje."]

    definition_pbir = folder / "definition.pbir"
    report_json = folder / "report.json"

    if definition_pbir.exists():
        try:
            json.loads(definition_pbir.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{definition_pbir} nie jest poprawnym JSON: {e}")
    elif report_json.exists():
        try:
            json.loads(report_json.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{report_json} nie jest poprawnym JSON: {e}")
    else:
        errors.append(f"Brak definition.pbir ani report.json w {folder}.")

    return errors


def _validate_semantic_model_folder(folder):
    errors = []
    folder = Path(folder)
    definition_dir = folder / "definition"

    if not definition_dir.exists():
        errors.append(f"Brak folderu definition/ w {folder} (oczekiwane pliki TMDL).")
        return errors

    tmdl_files = list(definition_dir.rglob("*.tmdl"))
    if not tmdl_files:
        errors.append(f"Brak plików .tmdl w {definition_dir}.")
        return errors

    for tmdl_file in tmdl_files:
        content = tmdl_file.read_text(encoding="utf-8")
        if not content.strip():
            errors.append(f"{tmdl_file} jest pusty.")
        # Lekka kontrola równowagi nawiasów klamrowych — nie pełna gramatyka TMDL,
        # tylko sygnał, że plik nie jest oczywiście urwany w połowie.
        if content.count("{") != content.count("}"):
            errors.append(f"{tmdl_file}: niezbalansowane nawiasy klamrowe — plik może być uszkodzony.")

    return errors


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else "mock_data/sample_pbip/Sales.Project"
    result = validate_pbip(target)
    print(json.dumps(result, ensure_ascii=False, indent=2))
