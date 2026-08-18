"""
Realne wykonanie zadania (nie stub) dla obsługiwanych typów — pierwszy prawdziwy
worker w pętli (M5 w skrócie). Dziś jedna zdolność: walidacja struktury PBIP
(PBI-01), która jest read-only i zielona, więc nadaje się na start autonomii bez
ryzyka. Typy nieobsługiwane zwracają None — runner_loop wraca wtedy do dotychczasowej
ścieżki "sama klasyfikacja/routing", nic nie udając.

Bezpieczeństwo: walidacja czyta pliki, więc ścieżkę zadania ograniczamy do jawnych
katalogów roboczych (ALLOWED_ROOTS) — zadanie nie może skierować workera na dowolny
punkt dysku. To lekki zalążek kontraktu uprawnień (pełny allowed_roots per narzędzie
to M1), nie jego zamiennik.
"""

from pathlib import Path

import pbip_validate

APP_DIR = Path(__file__).parent

# Katalogi, w których wolno walidować pliki. Ścieżka zadania musi się w nich
# zawierać po rozwinięciu (.resolve()), inaczej worker odmawia (fail-closed).
ALLOWED_ROOTS = [
    (APP_DIR / "mock_data").resolve(),
    (APP_DIR / "workspace").resolve(),
]


def execute(task):
    """Zwraca execution_result z REALNYM efektem, gdy typ zadania jest obsługiwany,
    albo None, gdy dla tego typu nie ma jeszcze workera."""
    if _is_pbip_validation(task):
        return _run_pbip_validation(task)
    return None


def _is_pbip_validation(task):
    if (task.get("action") or "").lower() == "validate_pbip":
        return True
    title = (task.get("title") or "").lower()
    return "pbip" in title and any(w in title for w in ("waliduj", "walidacj", "sprawdź struktur"))


def _path_within_allowed(path):
    resolved = Path(path).resolve()
    return any(resolved == root or root in resolved.parents for root in ALLOWED_ROOTS)


def _run_pbip_validation(task):
    raw_path = task.get("project_path") or task.get("source_file_link")
    if not raw_path:
        return _refused("Zadanie walidacji PBIP nie podało project_path.")

    if not _path_within_allowed(raw_path):
        return _refused(
            f"Ścieżka '{raw_path}' jest poza dozwolonymi katalogami roboczymi — worker odmawia (fail-closed)."
        )

    project_dir = Path(raw_path)
    if not project_dir.exists():
        return _refused(f"Ścieżka '{raw_path}' nie istnieje.")

    result = pbip_validate.validate_pbip(project_dir)
    passed = not result["errors"]
    target = str(project_dir)
    report = _build_report(project_dir, result, passed)
    return {
        "cost_usd": 0.0,  # czysta walidacja plików, bez modelu
        "tool": "validate_pbip",
        "executed": True,
        "acceptance_notes": report,  # pełny mini-raport, nie jedno zdanie (odbiór biznesowy)
        "output": result,  # sygnatura efektu dla Bartka (porównanie dwóch przebiegów)
        # Franek: twardy test funkcjonalny na realnym efekcie (ponowna walidacja pliku).
        "functional_checks": [
            {"name": "Walidacja struktury PBIP", "type": "pbip_valid", "target": target},
        ],
        # Bartek: drugi niezależny przebieg tej samej walidacji (kontrola determinizmu).
        "rerun": lambda: pbip_validate.validate_pbip(target),
    }


def _build_report(project_dir, result, passed):
    """Czytelny raport walidacji: CO sprawdzono, ILE plików, jakie błędy/ostrzeżenia.
    Bez tego odbiór biznesowy słusznie odrzuca ('jedno zdanie to nie raport')."""
    pbip = [f.name for f in project_dir.glob("*.pbip")]
    reports = [f.name for f in project_dir.glob("*.Report")]
    models = [f.name for f in project_dir.glob("*.SemanticModel")]
    tmdl_count = sum(len(list((m / "definition").rglob("*.tmdl"))) for m in project_dir.glob("*.SemanticModel"))

    lines = [
        f"Raport walidacji struktury PBIP — {project_dir.name}",
        f"Wynik: {'POPRAWNA' if passed else 'BŁĘDY'} — {len(result['errors'])} błędów, {len(result['warnings'])} ostrzeżeń.",
        "Sprawdzono:",
        f"  - pliki .pbip (poprawność JSON): {', '.join(pbip) or 'brak'}",
        f"  - foldery .Report (definition.pbir / report.json): {', '.join(reports) or 'brak'}",
        f"  - foldery .SemanticModel (pliki TMDL): {', '.join(models) or 'brak'} — {tmdl_count} {'plik' if tmdl_count == 1 else 'plików'} .tmdl",
    ]
    if result["errors"]:
        lines.append("Błędy:")
        lines.extend(f"  - {e}" for e in result["errors"])
    if result["warnings"]:
        lines.append("Ostrzeżenia:")
        lines.extend(f"  - {w}" for w in result["warnings"])
    return "\n".join(lines)


def _refused(reason):
    """Odmowa wykonania (np. ścieżka poza workspace). Runner obsługuje ją WPROST
    jako eskalację bezpieczeństwa — nie podajemy złej ścieżki dalej do bramki."""
    return {
        "cost_usd": 0.0,
        "tool": "validate_pbip",
        "executed": False,
        "acceptance_notes": reason,
        "output": {"refused": reason},
    }
