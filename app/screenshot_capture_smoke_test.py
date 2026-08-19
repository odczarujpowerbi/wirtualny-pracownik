"""
Test dymny screenshot_capture. NIE robi realnego zrzutu pulpitu (podmienia
backend na atrapę) — żeby cykliczny self_check nie zapisywał w kółko obrazu
ekranu użytkownika i był deterministyczny niezależnie od zainstalowanych bibliotek.

Użycie:
    python screenshot_capture_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import screenshot_capture


def _fake_grab(bbox, out_path):
    Path(out_path).write_bytes(b"\x89PNG\r\n_fake_")
    return out_path


def _raise_import(bbox, out_path):
    raise ImportError("brak backendu")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original = screenshot_capture._BACKENDS

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "shot.png"

        # Backend działa -> available True, plik zapisany.
        screenshot_capture._BACKENDS = (("fake", _fake_grab),)
        ok = screenshot_capture.capture_screen(out)
        checks.append(("capture_screen: backend OK -> available + plik istnieje",
                       ok["available"] and Path(ok["path"]).is_file()))

        # capture_region z poprawnym bbox.
        region = screenshot_capture.capture_region((0, 0, 100, 50), Path(tmp) / "r.png")
        checks.append(("capture_region: poprawny bbox -> available", region["available"]))

        # Brak backendu (ImportError) -> available False z powodem.
        screenshot_capture._BACKENDS = (("f", _raise_import),)
        no_backend = screenshot_capture.capture_screen(Path(tmp) / "x.png")
        checks.append(("capture_screen: brak backendu -> available False + detail",
                       no_backend["available"] is False and bool(no_backend["detail"])))

    screenshot_capture._BACKENDS = original

    # Niepoprawny bbox -> available False, bez próby przechwytywania.
    bad = screenshot_capture.capture_region((1, 2, 3), None)
    checks.append(("capture_region: zły bbox -> available False", bad["available"] is False))

    print("\n--- Wynik testu dymnego screenshot_capture ---")
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
