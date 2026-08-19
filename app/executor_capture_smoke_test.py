"""
Test dymny nowych zdolności executora: capture_screenshot i open_pbip_capture.
Podmienia realny zrzut/GUI na atrapy — sprawdza WPIĘCIE (kontrakt narzędzia,
kształt execution_result, screenshot_path, functional_checks), nie samo GUI.

Użycie:
    python executor_capture_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import executor
import pbi_desktop_bridge
import screenshot_capture


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    orig_win = screenshot_capture.capture_window
    orig_bridge = pbi_desktop_bridge.open_and_capture
    try:
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "efekt.png"
            shot.write_bytes(b"\x89PNG_fake")

            screenshot_capture.capture_window = lambda title, out=None: {
                "available": True, "path": str(shot), "backend": "fake", "detail": "OK"}
            res = executor.execute({"action": "capture_screenshot", "window_title": "Power BI"})
            checks.append(("capture_screenshot: screenshot_path ustawiony",
                           res is not None and res.get("screenshot_path") == str(shot)))
            checks.append(("capture_screenshot: functional_check nonempty_file",
                           any(c["type"] == "nonempty_file" for c in res.get("functional_checks", []))))

            pbi_desktop_bridge.open_and_capture = lambda p, **k: {
                "available": True, "screenshot_path": str(shot), "detail": "OK"}
            res2 = executor.execute({"action": "open_pbip_capture", "project_path": "mock_data/sample_pbip"})
            checks.append(("open_pbip_capture: tool + screenshot_path",
                           res2 and res2["tool"] == "open_pbip_capture" and res2["screenshot_path"] == str(shot)))
    finally:
        screenshot_capture.capture_window = orig_win
        pbi_desktop_bridge.open_and_capture = orig_bridge

    # Kontrakt: ścieżka PBIP poza allowed_roots -> odmowa (fail-closed).
    refused = executor.execute({"action": "open_pbip_capture", "project_path": "C:/Windows"})
    checks.append(("open_pbip_capture: ścieżka poza allowed_roots -> executed False",
                   refused is not None and refused.get("executed") is False))

    print("\n--- Wynik testu dymnego executor (zrzuty) ---")
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
