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

import ctypes  # tylko ctypes.windll (Windows) jest platformowe — używane w guardzie try/except
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


def _capture_hwnd_printwindow(hwnd, out_path):
    """Zrzut okna przez PrintWindow (PW_RENDERFULLCONTENT) — rysuje okno z bufora
    DWM, więc działa nawet gdy okno jest ZASŁONIĘTE i przeżywa ODŁĄCZENIE RDP
    (kluczowe dla agenta 24/7 na serwerze — zwykły grab framebuffera czernieje).
    Wymaga pywin32 + Pillow (lazy import)."""
    import win32gui
    import win32ui
    from PIL import Image

    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    width, height = right - left, bottom - top
    if width <= 0 or height <= 0:
        raise RuntimeError("okno ma zerowy rozmiar")

    window_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(window_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    try:
        PW_RENDERFULLCONTENT = 2
        ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), PW_RENDERFULLCONTENT)
        info = bitmap.GetInfo()
        bits = bitmap.GetBitmapBits(True)
        image = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
        image.save(out_path)
    finally:
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, window_dc)
    return out_path


def capture_window(window_title, out_path=None):
    """Zrzut konkretnego okna po fragmencie tytułu (case-insensitive). Podstawa
    pracy 'na wielu okienkach': agent zrzuca DOKŁADNIE to okno, nie pulpit.
    Preferuje PrintWindow/DWM (odporny na odłączenie RDP i zasłonięcie okna),
    a gdy niedostępny — spada na wysunięcie okna na wierzch + zrzut obszaru."""
    import window_manager  # lazy: unika cyklu importów

    win = window_manager.find_window(window_title)
    if win is None:
        return _result(False, None, None, f"Nie znaleziono okna dla '{window_title}'.")

    out_path = Path(out_path) if out_path else _default_out_path()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    hwnd = win.get("hwnd")
    if hwnd:
        try:
            _capture_hwnd_printwindow(int(hwnd), out_path)
            return _result(True, out_path, "printwindow", "OK (DWM — odporne na odłączenie RDP)")
        except Exception:  # noqa: BLE001 — brak pywin32/Pillow albo błąd PrintWindow -> zrzut obszaru
            pass

    window_manager.focus_window(window_title)
    bounds = window_manager.get_bounds(window_title)
    if bounds is None:
        return _result(False, None, None, f"Znaleziono okno '{window_title}', ale brak jego granic.")
    result = _capture(bounds, out_path)
    if result["available"]:
        result["detail"] = "OK (zrzut obszaru — UWAGA: czernieje po odłączeniu RDP)"
    return result


if __name__ == "__main__":
    print(capture_screen())
