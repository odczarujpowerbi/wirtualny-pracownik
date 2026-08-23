"""
Test dymny document_builder.py. Zero sieci — tylko lokalny zapis do
katalogu tymczasowego (nie runs/, żeby test nie zaśmiecał realnego wyjścia).
Sprawdza, że każdy format faktycznie tworzy niepusty plik z sensowną treścią
(dla .md — nagłówki + tabela markdown; dla .docx/.pdf — obecność i rozmiar).
Bez .qmd — decyzja właściciela 22.08.2026, patrz docstring document_builder.py.

Użycie:
    python document_builder_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import document_builder as db

DEMO_SECTIONS = [
    {"heading": "Kontekst", "text": "Pierwszy akapit.\n\nDrugi akapit."},
    {"heading": "Zestawienie", "table": {"rows": [
        {"Kanal": "Newsletter", "Wyslane": 1200, "Otwarcia": 480},
        {"Kanal": "Meta Ads", "Wyslane": 0, "Otwarcia": 0},
    ]}},
]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # 1. build_md: nagłówek + sekcje (tekst i tabela), bez żadnej zależności.
        md_path = db.build_md("Demo MD", DEMO_SECTIONS, tmp / "demo.md")
        md_text = md_path.read_text(encoding="utf-8")
        checks.append(("build_md: nagłówek H1 z tytułem", md_text.startswith("# Demo MD")))
        checks.append(("build_md: nagłówek sekcji H2", "## Kontekst" in md_text))
        checks.append(("build_md: tekst akapitu obecny", "Pierwszy akapit." in md_text))
        checks.append(("build_md: tabela markdown obecna", "| Kanal | Wyslane | Otwarcia |" in md_text))

        # 2. build_docx: plik niepusty, rozpoznawalny jako zip/docx (PK header).
        docx_path = db.build_docx("Demo DOCX", DEMO_SECTIONS, tmp / "demo.docx")
        docx_bytes = docx_path.read_bytes()
        checks.append(("build_docx: plik istnieje i nie jest pusty", len(docx_bytes) > 0))
        checks.append(("build_docx: sygnatura ZIP (docx to zip)", docx_bytes[:2] == b"PK"))

        # 3. build_pdf: plik niepusty, sygnatura %PDF.
        pdf_path = db.build_pdf("Demo PDF", DEMO_SECTIONS, tmp / "demo.pdf")
        pdf_bytes = pdf_path.read_bytes()
        checks.append(("build_pdf: plik istnieje i nie jest pusty", len(pdf_bytes) > 0))
        checks.append(("build_pdf: sygnatura %PDF", pdf_bytes[:4] == b"%PDF"))

        # 4. build_md tworzy katalog nadrzędny, gdy nie istnieje.
        nested = tmp / "podkatalog" / "zagniezdzony" / "demo.md"
        db.build_md("Nested", [{"text": "x"}], nested)
        checks.append(("build_md: tworzy brakujące katalogi nadrzędne", nested.exists()))

    print("\n--- Wynik testu dymnego document_builder ---")
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
