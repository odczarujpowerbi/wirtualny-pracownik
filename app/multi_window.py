"""
Praca na WIELU OKNACH naraz (do ~16) na duzym wirtualnym pulpicie sesji.

Model (uzgodniony): rozdzielczosc sesji jest niezalezna od tego, co widzisz przez
RDP — ustawiasz np. 7680x4320 i kafelkujesz 4x4 po Full HD, wiec aplikacje
renderuja sie w PELNYM rozmiarze (zadnych zwinietych wstazek/ukrytych opcji).

Petla agenta: co ~45 s zrob ZRZUTY wszystkich okien (rownolegle, watki — to
bezpieczne), przeanalizuj, a AKCJE (klikniecia) wykonuj PO KOLEI (jeden kursor/
fokus na sesje; serializacja przez ui_lock). Zrzuty per-okno ida przez
screenshot_capture.capture_window (PrintWindow/DWM — odporne na odlaczenie RDP).
"""

import math
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import screenshot_capture
import window_manager

SCAN_DIR = Path(__file__).parent / "runs" / "screenshots" / "scan"


def choose_grid(count):
    """Dobiera (kolumny, wiersze) dla count okien — kwadratowo (16 -> 4x4, 12 -> 4x3)."""
    if count <= 0:
        return (0, 0)
    cols = math.ceil(math.sqrt(count))
    rows = math.ceil(count / cols)
    return (cols, rows)


def plan_grid(count, screen_w, screen_h, padding=8, cols=None, rows=None):
    """Czysta matematyka siatki: zwraca liste (left, top, width, height) dla count
    komorek na pulpicie screen_w x screen_h. Testowalne bez okien."""
    if count <= 0 or screen_w <= 0 or screen_h <= 0:
        return []
    if not cols or not rows:
        cols, rows = choose_grid(count)
    cell_w, cell_h = screen_w // cols, screen_h // rows
    cells = []
    for i in range(count):
        row, col = divmod(i, cols)
        cells.append((col * cell_w + padding, row * cell_h + padding,
                      cell_w - 2 * padding, cell_h - 2 * padding))
    return cells


def _screen_size(screen_w, screen_h):
    if screen_w and screen_h:
        return screen_w, screen_h
    size = window_manager.virtual_screen_size()
    return size if size else (1920, 1080)


def arrange(title_queries, screen_w=None, screen_h=None, padding=8):
    """Kafelkuje podane okna w siatke na pulpicie. Zwraca liste wynikow per okno
    {title, ok, cell, detail}. Nie rzuca — brak okna = ok:False dla tej pozycji."""
    screen_w, screen_h = _screen_size(screen_w, screen_h)
    cells = plan_grid(len(title_queries), screen_w, screen_h, padding)
    results = []
    for query, (left, top, width, height) in zip(title_queries, cells):
        r = window_manager.move_resize(query, left, top, width, height)
        results.append({"title": query, "ok": r["ok"], "cell": (left, top, width, height),
                        "detail": r["detail"]})
    return results


def _safe_name(text):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", text)[:60] or "okno"


def capture_all(title_queries, out_dir=None, max_workers=8):
    """RÓWNOLEGLE zrzuca wszystkie podane okna (watki). Zwraca {title: wynik
    capture_window}. Bezpieczne: kazdy zrzut to niezalezne wywolanie DWM."""
    out_dir = Path(out_dir) if out_dir else SCAN_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    def _one(query):
        target = out_dir / f"{_safe_name(query)}.png"
        return query, screenshot_capture.capture_window(query, target)

    workers = max(1, min(max_workers, len(title_queries) or 1))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return dict(executor.map(_one, title_queries))


if __name__ == "__main__":
    print("grid 16 @ 7680x4320:", choose_grid(16), plan_grid(16, 7680, 4320)[:2], "...")
