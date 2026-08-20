"""
Akcje na UI przez UI Automation (pywinauto backend 'uia'). Nowoczesne aplikacje
(WPF, WinForms, Chromium, Power BI Desktop, VS Code) ignoruja klikanie przez
PostMessage/WM_LBUTTONDOWN — UIA klika ELEMENT (InvokePattern) pewnie i czesto
BEZ zabierania fokusu.

To warstwa AKCJI. Fokus i SERIALIZACJA (jedno okno na zadanie w danej chwili)
pilnuje ui_lock — w jednej sesji jest jeden kursor/fokus, wiec akcje ida po kolei,
a rownolegle robi sie tylko zrzuty (multi_window.capture_all).

Degraduje sie lagodnie: brak pywinauto / nie-Windows -> {ok: False} z powodem,
nigdy nie rzuca (pętla agenta ma isc dalej i eskalowac, nie wywalac sie).
"""

import re


def available():
    try:
        import pywinauto  # noqa: F401
        return {"available": True, "detail": "pywinauto (uia) dostepne"}
    except ImportError:
        return {"available": False, "detail": "Brak pywinauto (pip install pywinauto)"}


def _window(title_query):
    """Uchwyt okna UIA po fragmencie tytulu. Rzuca, gdy brak backendu/okna —
    wolajacy (funkcje publiczne nizej) lapie i zwraca {ok: False}."""
    from pywinauto import Desktop

    pattern = f".*{re.escape(title_query)}.*"
    win = Desktop(backend="uia").window(title_re=pattern)
    win.wait("exists", timeout=5)
    return win


def _find(win, control_name, control_type=None):
    kwargs = {"title": control_name}
    if control_type:
        kwargs["control_type"] = control_type
    return win.child_window(**kwargs)


def click(title_query, control_name, control_type=None):
    """Klika element o nazwie control_name w oknie. Preferuje InvokePattern
    (bez zabierania fokusu); gdy element go nie wspiera — klik myszy. {ok, detail}."""
    try:
        element = _find(_window(title_query), control_name, control_type)
        element.wait("exists enabled visible", timeout=5)
        try:
            element.invoke()  # InvokePattern — nie zabiera fokusu
            how = "invoke"
        except Exception:  # noqa: BLE001 — element bez InvokePattern -> realny klik
            element.click_input()
            how = "click_input"
        return {"ok": True, "detail": f"Klik '{control_name}' ({how})"}
    except Exception as exc:  # noqa: BLE001 — brak okna/elementu/backendu
        return {"ok": False, "detail": f"Nie udalo sie kliknac '{control_name}': {exc}"}


def set_text(title_query, control_name, text, control_type="Edit"):
    """Wpisuje tekst do pola. {ok, detail}."""
    try:
        element = _find(_window(title_query), control_name, control_type)
        element.wait("exists enabled visible", timeout=5)
        element.set_edit_text(text)
        return {"ok": True, "detail": f"Wpisano tekst do '{control_name}'"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"Nie udalo sie wpisac do '{control_name}': {exc}"}


def list_controls(title_query, limit=60):
    """Lista klikalnych/istotnych elementow okna (nazwa + typ) — pozwala agentowi
    'zobaczyc opcje' bez OCR. Zwraca {ok, controls, detail}."""
    try:
        win = _window(title_query)
        items = []
        for ctrl in win.descendants():
            try:
                name = ctrl.window_text()
                ctype = ctrl.element_info.control_type
            except Exception:  # noqa: BLE001 — pojedynczy element bez dostepu
                continue
            if name and name.strip():
                items.append({"name": name.strip(), "type": ctype})
            if len(items) >= limit:
                break
        return {"ok": True, "controls": items, "detail": f"{len(items)} elementow"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "controls": [], "detail": f"Nie udalo sie odczytac okna: {exc}"}


if __name__ == "__main__":
    print(available())
