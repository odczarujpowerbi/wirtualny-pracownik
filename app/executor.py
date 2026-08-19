"""
Realne wykonanie zadania (nie stub) dla obsługiwanych typów — pierwszy prawdziwy
worker w pętli (M5 w skrócie). Dziś jedna zdolność: walidacja struktury PBIP
(PBI-01), która jest read-only i zielona, więc nadaje się na start autonomii bez
ryzyka. Typy nieobsługiwane zwracają None — runner_loop wraca wtedy do dotychczasowej
ścieżki "sama klasyfikacja/routing", nic nie udając.

Bezpieczeństwo (M1): KAŻDE wykonanie przechodzi przez tool_registry.check_call —
narzędzie musi być w rejestrze kontraktów (config/tool_contracts.yaml), a jego
parametry (w tym ścieżki wobec allowed_roots) muszą pasować do kontraktu. Odmowa
kontraktu = worker nie wykonuje nic (fail-closed). Executor nie trzyma już własnej
listy ścieżek — źródłem prawdy jest kontrakt.
"""

from pathlib import Path

import pbi_desktop_bridge
import pbip_validate
import screenshot_capture
import tool_registry


def execute(task):
    """Zwraca execution_result z REALNYM efektem, gdy typ zadania jest obsługiwany,
    albo None, gdy dla tego typu nie ma jeszcze workera."""
    action = (task.get("action") or "").lower()
    if _is_pbip_validation(task):
        return _run_pbip_validation(task)
    if action == "capture_screenshot":
        return _run_screenshot_capture(task)
    if action == "open_pbip_capture":
        return _run_pbip_capture(task)
    return None


def _is_pbip_validation(task):
    if (task.get("action") or "").lower() == "validate_pbip":
        return True
    title = (task.get("title") or "").lower()
    return "pbip" in title and any(w in title for w in ("waliduj", "walidacj", "sprawdź struktur"))


def _run_pbip_validation(task):
    raw_path = task.get("project_path") or task.get("source_file_link")

    # M1: bramka kontraktu PRZED jakimkolwiek dostępem do plików. Rejestr sprawdza
    # allowlistę narzędzia, wymagane parametry i allowed_roots dla ścieżki.
    check = tool_registry.check_call("validate_pbip", {"project_path": raw_path})
    if not check["allowed"]:
        return _refused(check["reason"])

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


def _screenshot_effect(shot, tool, ok_notes, fail_notes):
    """Wspólny kształt execution_result dla zadań, których efektem jest ZRZUT
    ekranu — karmi Oskara (kontrola wizualna) i Franka (nonempty_file na PNG)."""
    if not shot["available"]:
        # Brak zrzutu to nie odmowa bezpieczeństwa, tylko luka zdolności —
        # przechodzi przez bramkę uczciwie (Oskar pominie brak zrzutu).
        return {"cost_usd": 0.0, "tool": tool, "executed": True,
                "acceptance_notes": f"{fail_notes} Szczegół: {shot['detail']}"}
    return {
        "cost_usd": 0.0,
        "tool": tool,
        "executed": True,
        "acceptance_notes": f"{ok_notes} Zrzut: {shot['screenshot_path']}",
        "screenshot_path": shot["screenshot_path"],
        "functional_checks": [
            {"name": "Zrzut ekranu zapisany", "type": "nonempty_file", "target": shot["screenshot_path"]},
        ],
    }


def _run_screenshot_capture(task):
    """Zrzut ekranu/okna jako efekt zadania (np. 'pokaż stan aplikacji X')."""
    out_dir = task.get("out_dir")
    check = tool_registry.check_call("capture_screenshot", {"out_dir": out_dir})
    if not check["allowed"]:
        return _refused(check["reason"], tool="capture_screenshot")

    window_title = task.get("window_title")
    if window_title:
        shot = screenshot_capture.capture_window(window_title)
        # capture_window zwraca {available, path, ...}; ujednolicamy do kształtu bridge.
        shot = {"available": shot["available"], "screenshot_path": shot.get("path"), "detail": shot["detail"]}
    else:
        raw = screenshot_capture.capture_screen()
        shot = {"available": raw["available"], "screenshot_path": raw.get("path"), "detail": raw["detail"]}
    return _screenshot_effect(shot, "capture_screenshot",
                              "Zrzut ekranu wykonany.", "Nie udało się wykonać zrzutu.")


def _run_pbip_capture(task):
    """Otwiera PBIP w Power BI Desktop i robi zrzut okna raportu (PBI-01, dalszy
    etap po walidacji struktury) — dostarcza screenshot_path do kontroli wizualnej."""
    raw_path = task.get("project_path") or task.get("source_file_link")
    check = tool_registry.check_call("open_pbip_capture", {"project_path": raw_path})
    if not check["allowed"]:
        return _refused(check["reason"], tool="open_pbip_capture")

    shot = pbi_desktop_bridge.open_and_capture(raw_path)
    result = _screenshot_effect(shot, "open_pbip_capture",
                                "Otwarto PBIP i wykonano zrzut strony raportu.",
                                "Otwarcie/zrzut raportu nie powiodły się.")
    result["tool"] = "open_pbip_capture"
    return result


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


def _refused(reason, tool="validate_pbip"):
    """Odmowa wykonania (np. ścieżka poza workspace). Runner obsługuje ją WPROST
    jako eskalację bezpieczeństwa — nie podajemy złej ścieżki dalej do bramki."""
    return {
        "cost_usd": 0.0,
        "tool": tool,
        "executed": False,
        "acceptance_notes": reason,
        "output": {"refused": reason},
    }
