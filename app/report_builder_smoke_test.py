"""
Test dymny report_builder.py. Zero sieci. Sprawdza markdown/CSV (biblioteka
standardowa) i XLSX (openpyxl) — w tym sanityzację nazwy arkusza, bo `title[:31]`
samo w sobie NIE wystarcza (openpyxl rzuca ValueError na \\ / * ? : [ ], nie
tylko na długość — złapane 22.08.2026 na tytule z ukośnikiem "EUR/PLN").

Użycie:
    python report_builder_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import report_builder as rb

ROWS = [{"A": 1, "B": 2}, {"A": 3, "B": 4}]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. build_markdown_table: nagłówek + separator + wiersze.
    md = rb.build_markdown_table(ROWS)
    checks.append(("build_markdown_table: nagłówek kolumn", "| A | B |" in md))
    checks.append(("build_markdown_table: brak danych -> komunikat, nie wyjątek",
                   rb.build_markdown_table([]) == "_(brak danych)_"))

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 2. write_csv_report: plik istnieje, ma nagłówek.
        csv_path = rb.write_csv_report(ROWS, tmp / "demo.csv")
        csv_text = csv_path.read_text(encoding="utf-8") if hasattr(csv_path, "read_text") else open(csv_path, encoding="utf-8").read()
        checks.append(("write_csv_report: nagłówek kolumn w pliku", "A,B" in csv_text))

        # 3. _xlsx_sheet_title: sanityzacja znaków niedozwolonych w Excelu.
        checks.append(("_xlsx_sheet_title: usuwa ukośnik", "/" not in rb._xlsx_sheet_title("EUR/PLN")))
        checks.append(("_xlsx_sheet_title: usuwa dwukropek/gwiazdkę/nawiasy kwadratowe",
                       not any(c in rb._xlsx_sheet_title("a:b*c[d]e") for c in ":*[]")))
        checks.append(("_xlsx_sheet_title: limit 31 znaków", len(rb._xlsx_sheet_title("x" * 50)) <= 31))
        checks.append(("_xlsx_sheet_title: pusty tytuł -> 'Raport'", rb._xlsx_sheet_title("") == "Raport"))

        # 4. build_report(xlsx): tytuł z ukośnikiem (przypadek, który padał na produkcji) -> nie rzuca.
        xlsx_path = rb.build_report("Historia EUR/PLN — 7 dni", ROWS, output_format="xlsx", output_path=tmp / "demo.xlsx")
        checks.append(("build_report xlsx: tytuł z ukośnikiem nie wywala zapisu", Path(xlsx_path).exists()))
        checks.append(("build_report xlsx: plik niepusty", Path(xlsx_path).stat().st_size > 0))

        # 5. build_report: brak output_path dla csv/xlsx -> ValueError (nie crash bez komunikatu).
        for fmt in ("csv", "xlsx"):
            try:
                rb.build_report("T", ROWS, output_format=fmt)
                raised = False
            except ValueError:
                raised = True
            checks.append((f"build_report {fmt}: brak output_path -> ValueError", raised))

        # 6. build_report: format nieznany -> ValueError.
        try:
            rb.build_report("T", ROWS, output_format="docx")
            raised = False
        except ValueError:
            raised = True
        checks.append(("build_report: nieznany output_format -> ValueError", raised))

    print("\n--- Wynik testu dymnego report_builder ---")
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
