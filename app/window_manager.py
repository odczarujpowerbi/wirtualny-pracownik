"""
Zarządzanie oknami — podstawa pracy "na wielu okienkach" (przeplyw.html sekcja
kilka ekranów/repozytoriów naraz, wcześniej pusta). Pozwala agentowi:
  - wylistować otwarte okna (tytuł + geometria),
  - znaleźć okno po fragmencie tytułu,
  - wysunąć okno na wierzch (focus) przed działaniem/zrzutem,
  - odczytać jego granice (dla screenshot_capture.capture_window).

Reguła "jedno aktywne okno na zadanie" (serializacja computer use) żyje w
ui_lock.py — tu jest sama warstwa okien.

Backend: pygetwindow (prosty) -> pywinauto (UI Automation, pewniejszy dla aplikacji
desktopowych). Lazy import, łagodna degradacja: bez backendu list_windows zwraca []
i available=False — nigdy nie rzuca.
"""


def _match(title, query):
    """Dopasowanie okna: fragment tytułu, case-insensitive. Wydzielone, bo to
    jedyna nietrywialna logika, którą chcemy testować bez systemu okien."""
    if not title or not query:
        return False
    return query.strip().lower() in title.lower()


def _via_pygetwindow():
    import pygetwindow as gw  # lazy: opcjonalna zależność

    windows = []
    for win in gw.getAllWindows():
        title = getattr(win, "title", "") or ""
        if not title.strip():
            continue
        windows.append({
            "title": title,
            "left": win.left, "top": win.top,
            "width": win.width, "height": win.height,
            "_handle": win,
        })
    return windows


def _via_pywinauto():
    from pywinauto import Desktop  # lazy: opcjonalna zależność

    windows = []
    for win in Desktop(backend="uia").windows():
        try:
            title = win.window_text() or ""
            if not title.strip():
                continue
            rect = win.rectangle()
            windows.append({
                "title": title,
                "left": rect.left, "top": rect.top,
                "width": rect.width(), "height": rect.height(),
                "_handle": win,
            })
        except Exception:  # noqa: BLE001 — pojedyncze okno bez dostępu nie psuje listy
            continue
    return windows


_BACKENDS = (("pygetwindow", _via_pygetwindow), ("pywinauto", _via_pywinauto))


def available():
    for name, _ in _BACKENDS:
        try:
            __import__("pygetwindow" if name == "pygetwindow" else "pywinauto")
            return {"available": True, "backend": name}
        except ImportError:
            continue
    return {"available": False, "backend": None}


def list_windows():
    """Wszystkie widoczne okna z tytułem. Pusta lista, gdy brak backendu."""
    for _, fetch in _BACKENDS:
        try:
            return fetch()
        except ImportError:
            continue
        except Exception:  # noqa: BLE001 — backend obecny, ale zawiódł: próbuj kolejnego
            continue
    return []


def find_window(title_query):
    """Pierwsze okno, którego tytuł zawiera title_query. None, gdy brak/niedostępne."""
    for win in list_windows():
        if _match(win["title"], title_query):
            return win
    return None


def get_bounds(title_query):
    """(left, top, width, height) okna albo None."""
    win = find_window(title_query)
    if win is None:
        return None
    return (win["left"], win["top"], win["width"], win["height"])


def focus_window(title_query):
    """Wysuwa okno na wierzch. Zwraca {ok, detail}. Nie rzuca."""
    win = find_window(title_query)
    if win is None:
        return {"ok": False, "detail": f"Nie znaleziono okna dla '{title_query}'."}
    handle = win.get("_handle")
    try:
        if hasattr(handle, "activate"):
            handle.activate()          # pygetwindow
        elif hasattr(handle, "set_focus"):
            handle.set_focus()         # pywinauto
        else:
            return {"ok": False, "detail": "Backend nie wspiera wysunięcia okna na wierzch."}
        return {"ok": True, "detail": f"Okno '{win['title']}' na wierzchu."}
    except Exception as exc:  # noqa: BLE001 — nieudany focus to nie crash agenta
        return {"ok": False, "detail": f"Nie udało się wysunąć okna: {exc}"}


if __name__ == "__main__":
    print(available())
    for w in list_windows()[:15]:
        print(f"  {w['title']!r} @ ({w['left']},{w['top']}) {w['width']}x{w['height']}")
