"""
Most do Power BI Desktop — otwiera projekt PBIP i robi zrzut okna raportu. To
brakujące ogniwo, które KARMI bota wizyjnego Oskara: dotąd nikt nie produkował
execution_result['screenshot_path'], więc kontrola wizualna nie miała czego
oglądać. Tu powstaje realny zrzut strony raportu.

UCZCIWIE: tej ścieżki GUI nie da się zweryfikować bez prawdziwego Windows z
zainstalowanym Power BI Desktop. Kod jest napisany defensywnie i degraduje się
łagodnie (available=False z powodem), gdy: nie-Windows, brak backendu okien, brak
backendu zrzutu, albo okno Power BI nie pojawiło się w zadanym czasie. Nigdy nie
rzuca — pętla agenta ma iść dalej i eskalować, nie wywalać się.
"""

import os
import sys
import time
from pathlib import Path

import screenshot_capture
import window_manager

WINDOW_TITLE_HINT = os.environ.get("PBI_WINDOW_TITLE", "Power BI")
DEFAULT_WAIT_SECONDS = 45
POLL_INTERVAL_SECONDS = 2


def _result(available, screenshot_path=None, detail=""):
    return {"available": available,
            "screenshot_path": str(screenshot_path) if screenshot_path else None,
            "detail": detail}


def _launch(project_path):
    """Otwiera PBIP domyślną aplikacją systemu (Power BI Desktop). Zwraca (ok, detail)."""
    if not sys.platform.startswith("win"):
        return False, f"Otwieranie PBIP wspierane tylko na Windows (system: {sys.platform})."
    try:
        os.startfile(str(project_path))  # noqa: S606 — Windows-only, ścieżka walidowana wcześniej
        return True, "Uruchomiono otwarcie PBIP."
    except OSError as exc:
        return False, f"Nie udało się otworzyć PBIP: {exc}"


def _wait_for_window(title_hint, wait_seconds, sleep=time.sleep):
    """Czeka aż pojawi się okno pasujące do title_hint. `sleep` wstrzykiwalny
    w testach. Zwraca True, gdy okno się pojawiło."""
    deadline = wait_seconds
    elapsed = 0
    while elapsed <= deadline:
        if window_manager.find_window(title_hint) is not None:
            return True
        sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
    return False


def open_and_capture(project_path, out_path=None, wait_seconds=DEFAULT_WAIT_SECONDS,
                     title_hint=None, sleep=time.sleep):
    """Otwiera PBIP i zwraca zrzut okna raportu: {available, screenshot_path, detail}.
    `sleep` wstrzykiwalny, żeby test nie czekał realnych sekund."""
    title_hint = title_hint or WINDOW_TITLE_HINT
    path = Path(project_path)
    if not path.exists():
        return _result(False, None, f"Ścieżka PBIP nie istnieje: {project_path}")

    launched, launch_detail = _launch(path)
    if not launched:
        return _result(False, None, launch_detail)

    if not window_manager.available()["available"]:
        return _result(False, None,
                       "Brak backendu okien (zainstaluj `pygetwindow` albo `pywinauto`) "
                       "— nie mogę znaleźć okna Power BI ani zrobić zrzutu strony.")

    if not _wait_for_window(title_hint, wait_seconds, sleep=sleep):
        return _result(False, None,
                       f"Okno '{title_hint}' nie pojawiło się w ciągu {wait_seconds}s "
                       "(Power BI się nie otworzył albo inny tytuł okna).")

    shot = screenshot_capture.capture_window(title_hint, out_path)
    if not shot["available"]:
        return _result(False, None, f"Okno jest, ale zrzut się nie udał: {shot['detail']}")
    return _result(True, shot["path"], "OK — zrzut okna raportu Power BI.")


if __name__ == "__main__":
    print(open_and_capture(sys.argv[1] if len(sys.argv) > 1 else "mock_data/sample_pbip"))
