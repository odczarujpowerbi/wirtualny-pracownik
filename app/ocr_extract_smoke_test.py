"""
Test dymny ocr_extract. Sprawdza łagodną degradację (brak pliku / brak backendu)
i logikę contains_number, bez zależności od zainstalowanego Tesseractu ani klucza.

Użycie:
    python ocr_extract_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import ocr_extract


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    missing = ocr_extract.extract_text("nie_ma_takiego_pliku_123.png")
    checks.append(("extract_text: brak pliku -> available False + detail",
                   missing["available"] is False and "nie istnieje" in missing["detail"]))

    # Plik istnieje, ale nie jest obrazem — OCR ma się zdegradować, nie wywalić.
    with tempfile.TemporaryDirectory() as tmp:
        junk = Path(tmp) / "nie_obraz.png"
        junk.write_bytes(b"to nie jest obraz")
        res = ocr_extract.extract_text(str(junk))
        checks.append(("extract_text: nie-obraz -> nie rzuca, zwraca kontrakt",
                       set(res.keys()) == {"available", "text", "source", "detail"}))

    checks.append(("contains_number: 1234,50 pasuje do 1234.5",
                   ocr_extract.contains_number("Suma: 1 234,50 zł", 1234.5, tolerance=0.01)))
    checks.append(("contains_number: 1,234.50 (en) pasuje do 1234.5",
                   ocr_extract.contains_number("Total 1,234.50 USD", 1234.5, tolerance=0.01)))
    checks.append(("contains_number: brak dopasowania",
                   ocr_extract.contains_number("Suma: 10", 999, tolerance=0.0) is False))
    checks.append(("contains_number: pusty tekst -> False",
                   ocr_extract.contains_number("", 1, 0) is False))

    print("\n--- Wynik testu dymnego ocr_extract ---")
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
