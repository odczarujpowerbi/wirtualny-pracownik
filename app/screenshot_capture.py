"""
Zrzut ekranu efektu — fundament agenta lokalnego, którego brakowało (przeplyw.html
sekcja 4: "model lokalny weryfikuje, robi screeny"). Bez tego bot wizyjny Oskar
nie ma czego oglądać (execution_result['screenshot_path'] nikt nie produkował).

Robi zrzut CAŁEGO ekranu, wskazanego OBSZARU albo KONKRETNEGO OKNA (po tytule,
przez window_manager). Zapis do runs/screenshots/ (runtime, w .gitignore).

Degraduje się łagodnie: gdy brak backendu przechwytywania (mss / Pillow), zwraca
available=False z jasnym powodem — nigdy nie rzuca, żeby nie wywalić pętli agenta.
Backendy próbowane po kolei: mss (lekki, wieloplatformowy) -> PIL.ImageGrab
(Windows/macOS, część Pillow).
"""

from datetime import datetime, timezone
from pathlib import Path

SCREENSHOT_DIR = Path(__file__).parent / "runs" / "screenshots"


def _default_out_path():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return SCREENSHOT_DIR / f"shot_{stamp}.png"


def _result(available, path=None, backend=None, detail=""):
    return {"available": available, "path": str(path) if path else None,
            "backend": backend, "detail": detail}


def _grab_mss(bbox, out_path):
    """bbox = (left, top, width, height) albo None (cały ekran wirtualny)."""
    import mss  # lazy: opcjonalna zależność
    import mss.tools

    with mss.mss() as sct:
        if bbox is None:
            monitor = sct.monitors[0]  # [0] = suma wszystkich monitorów
        else:
            left, top, width, height = bbox
            monitor = {"left": left, "top": top, "width": width, "height": height}
        image = sct.grab(monitor)
        mss.tools.to_png(image.rgb, image.size, output=str(out_path))
    return out_path


def _grab_pillow(bbox, out_path):
    from PIL import ImageGrab  # lazy: część Pillow, tylko Windows/macOS

    if bbox is None:
        image = ImageGrab.grab(all_screens=True)
    else:
        left, top, width, height = bbox
        image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    image.save(out_path)
    return out_path


_BACKENDS = (("mss", _grab_mss), ("pillow", _grab_pillow))


def _capture(bbox, out_path):
    out_path = Path(out_path) if out_path else _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    errors = []
    for name, grab in _BACKENDS:
        try:
            grab(bbox, out_path)
            return _result(True, out_path, name, "OK")
        except ImportError:
            continue  # backend niezainstalowany — próbujemy kolejnego
        except Exception as exc:  # noqa: BLE001 — błąd przechwytywania nie może wywalić agenta
            errors.append(f"{name}: {exc}")

    detail = ("Brak backendu przechwytywania ekranu (zainstaluj `mss` albo `Pillow`)."
              if not errors else "Przechwytywanie nie powiodło się: " + "; ".join(errors))
    return _result(False, None, None, detail)


def capture_screen(out_path=None):
    """Zrzut całego ekranu (wszystkie monitory). Zwraca {available, path, backend, detail}."""
    return _capture(None, out_path)


def capture_region(bbox, out_path=None):
    """Zrzut obszaru bbox=(left, top, width, height)."""
    if not (isinstance(bbox, (tuple, list)) and len(bbox) == 4):
        return _result(False, None, None, "bbox musi być krotką (left, top, width, height).")
    return _capture(tuple(bbox), out_path)


def capture_window(window_title, out_path=None):
    """Zrzut konkretnego okna po fragmencie tytułu (case-insensitive). Okno jest
    najpierw wysuwane na wierzch (focus), potem przechwytywany jest jego obszar —
    to podstawa pracy 'na wielu okienkach': agent zrzuca DOKŁADNIE to okno, nie pulpit."""
    import window_manager  # lazy: unika cyklu importów

    focus = window_manager.focus_window(window_title)
    bounds = window_manager.get_bounds(window_title)
    if bounds is None:
        return _result(False, None, None,
                       f"Nie znaleziono okna dla '{window_title}' ({focus.get('detail', '')}).")
    return _capture(bounds, out_path)


if __name__ == "__main__":
    print(capture_screen())
