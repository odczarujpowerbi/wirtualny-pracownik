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
from urllib.parse import urlparse

import pbi_desktop_bridge
import pbip_validate
import screenshot_capture
import tool_registry
import validator_prompt
import web_answer
import web_fetch_worker


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
    if action == "fetch_url":
        return _run_web_fetch(task)
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


def _run_web_fetch(task):
    """Pobranie informacji z internetu (read-only GET). Allowlista hostów siedzi
    w kontrakcie `fetch_url` — executor nie trzyma własnej listy, tak samo jak
    przy ścieżkach plików.

    Treść z internetu jest z definicji NIEZAUFANA, więc zanim trafi do modelu
    przechodzi przez kontrolę wstrzyknięcia instrukcji. Wykrycie = odmowa
    z eskalacją, nie 'ostrzeżenie w raporcie'."""
    url = task.get("url") or task.get("source_file_link")
    check = tool_registry.check_call("fetch_url", {"url": url})
    if not check["allowed"]:
        return _refused(check["reason"], tool="fetch_url")

    contract = tool_registry.get_contract("fetch_url") or {}
    result = web_fetch_worker.fetch(url, allowed_hosts=tool_registry.allowed_domains(contract))
    if not result["available"]:
        # Niepowodzenie pobrania to luka dostępności źródła, nie odmowa
        # bezpieczeństwa — idzie przez bramkę uczciwie, z powodem.
        return {"cost_usd": 0.0, "tool": "fetch_url", "executed": True,
                "acceptance_notes": f"Nie udało się pobrać danych z {url}. Szczegół: {result['detail']}",
                "output": _web_signature(result)}

    safety = validator_prompt.check_prompt_safety(result["text"][:4000])
    if not safety["safe"]:
        return _refused(
            f"Pobrana treść z '{url}' wygląda na próbę wstrzyknięcia instrukcji "
            f"({safety['detail']}) — treść NIE jest podawana dalej do modelu. Plik: {result['saved_path']}",
            tool="fetch_url")

    # Samo pobranie to jeszcze nie wykonanie zadania — model odpowiada na pytanie
    # z tytułu zadania na podstawie treści. Bez tego kroku odbiór biznesowy
    # słusznie odrzuca surowy JSON jako "efekt" (realny werdykt Bożeny).
    answer = web_answer.answer(task.get("title", ""), result["text"], url=url)

    return {
        "cost_usd": answer.get("cost_usd", 0.0),
        "tool": "fetch_url",
        "executed": True,
        "acceptance_notes": _build_web_report(result, answer),
        "output": _web_signature(result),
        "functional_checks": [
            {"name": "Pobrana treść zapisana na dysku", "type": "nonempty_file", "target": result["saved_path"]},
        ],
        # Bartek porównuje SYGNATURY, więc rerun musi zwracać dokładnie ten sam
        # kształt co `output` — inaczej każde zadanie wygląda na niedeterministyczne
        # (realnie napotkane na pierwszym przebiegu).
        "rerun": lambda: _web_signature(web_fetch_worker.fetch(
            url, allowed_hosts=tool_registry.allowed_domains(tool_registry.get_contract("fetch_url") or {}))),
    }


def _web_signature(result):
    """Sygnatura pobrania do kontroli regresji (Bartek): CO odpowiedziało źródło,
    a nie co dokładnie było w treści. Żywe strony zmieniają w każdej odpowiedzi
    identyfikatory i znaczniki czasu (np. pole `tid` w API Wikipedii), więc
    porównywanie pełnej treści dawałoby stały fałszywy alarm 'niedeterminizm'.
    Merytoryczną zawartość ocenia Franek (plik) i Bożena (odbiór)."""
    if not result.get("available"):
        return {"available": False, "url": result.get("url"), "detail": result.get("detail")}
    return {
        "available": True,
        "url": result["url"],
        "final_url": result["final_url"],
        "human_url": result.get("human_url"),
        "status": result["status"],
        "content_type": result["content_type"],
        "title": result["title"],
    }


def _source_label(result):
    """Opis źródła dla człowieka: nazwa instytucji z kontraktu + klikalny link
    w nawiasie. Sam adres API jest dla odbiorcy nieczytelny — realna uwaga
    z odbioru biznesowego ("chcę 'NBP, tabela nr ...', link może być w nawiasie")."""
    link = result.get("human_url") or result.get("url") or ""
    host = urlparse(link).hostname or ""
    nazwy = (tool_registry.get_contract("fetch_url") or {}).get("source_names") or {}
    nazwa = nazwy.get(host)
    return f"{nazwa} ({link})" if nazwa else link


def _build_web_report(result, answer=None):
    """Materiał dla ODBIORCY: odpowiedź na zadanie + klikalne źródło i data pobrania.
    Dane techniczne (status HTTP, rozmiar, lokalna ścieżka pliku) celowo NIE trafiają
    tutaj — odbiór biznesowy słusznie zauważył, że w materiale dla klienta nie mają
    czego szukać, a ścieżka ujawnia strukturę katalogów maszyny. Zostają w `output`
    i w kontroli funkcjonalnej, czyli tam, gdzie służą audytowi."""
    stopka = f"Źródło: {_source_label(result)}, pobrano {result.get('fetched_at', 'dziś')}."

    if answer and answer.get("available"):
        return f"{answer['answer']}\n\n{stopka}"

    powod = answer["detail"] if answer else "brak modelu"
    return "\n".join([
        f"UWAGA: nie udało się opracować odpowiedzi modelem ({powod}) — poniżej surowa treść źródła.",
        "",
        result["text"][:1500],
        "",
        stopka,
    ])


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
