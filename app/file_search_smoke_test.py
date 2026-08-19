"""
Test dymny file_search. Sprawdza find_files i search_content na tymczasowym
drzewie plików ORAZ bezpośrednio czysty fallback (_search_python), żeby ścieżka
bez ripgrep była pokryta niezależnie od tego, czy `rg` jest w PATH.

Użycie:
    python file_search_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import file_search


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "a.txt").write_text("Miara Sprzedaz\ndrugi wiersz\n", encoding="utf-8")
        (root / "b.tmdl").write_text("measure Sprzedaz = SUM(x)\n", encoding="utf-8")
        (root / "sub").mkdir()
        (root / "sub" / "c.txt").write_text("nic tu nie ma\n", encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "skip.txt").write_text("SPRZEDAZ w cache\n", encoding="utf-8")

        tmdl = file_search.find_files(root, "*.tmdl")
        checks.append(("find_files: znajduje *.tmdl", len(tmdl) == 1 and tmdl[0].endswith("b.tmdl")))

        txt = file_search.find_files(root, "**/*.txt")
        checks.append(("find_files: pomija __pycache__",
                       any("a.txt" in p for p in txt) and not any("skip.txt" in p for p in txt)))

        hits = file_search.search_content(root, "sprzedaz", ignore_case=True)
        checks.append(("search_content: znajduje w 2 plikach (case-insensitive)",
                       len({h["path"] for h in hits}) == 2))

        none = file_search.search_content(root, "czegotutajniema12345")
        checks.append(("search_content: brak trafień -> []", none == []))

        limited = file_search.search_content(root, "sprzedaz", max_results=1)
        checks.append(("search_content: respektuje max_results", len(limited) == 1))

        # Bezpośrednio czysty fallback (bez ripgrep).
        py = file_search._search_python(root, "measure", None, 100, True)
        checks.append(("_search_python: fallback znajduje 'measure'",
                       any("b.tmdl" in h["path"] for h in py)))

    empty = file_search.search_content("sciezka_ktora_nie_istnieje_xyz", "x")
    checks.append(("search_content: nieistniejący root -> []", empty == []))

    print("\n--- Wynik testu dymnego file_search ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
