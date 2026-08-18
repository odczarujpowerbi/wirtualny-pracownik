"""
self_check.py — samo-weryfikacja mechanizmu.

Odpowiedź na wprost zadane pytanie: "skąd wiem, że po dodaniu skilla/funkcji nic
się nie zepsuło". Uruchamia WSZYSTKIE testy dymne (*_smoke_test.py) w folderze
app, każdy w osobnym procesie (izolacja — jeden zepsuty test nie ubija reszty),
i raportuje, czy całość działa.

Wpięte w scheduler (config/schedule.yaml, job `self_check`), więc wynik ląduje w
dashboardzie automatycznie: zielony gdy wszystko przechodzi, CZERWONY gdy
którykolwiek test padł — a po kliknięciu w przebieg widać pełne wyjście: który
test i dlaczego (dashboard zapisuje stdout+stderr każdego przebiegu).

run_self_check() (bezargumentowe, dla schedulera) RZUCA wyjątek, gdy którykolwiek
test nie przeszedł — dzięki temu scheduler oznacza przebieg jako 'error'.
Uruchamiane też ręcznie: python self_check.py
"""

import os
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).parent
TEST_GLOB = "*_smoke_test.py"
PER_TEST_TIMEOUT = 180

# Testy WYKLUCZONE z ciągłej samo-weryfikacji, z powodem. bootstrap_smoke_test
# przełącza GLOBALNY kill switch i pisze do prawdziwego runs/state.db — to test
# odbioru maszyny (uruchamiany raz, ręcznie), nie regresja kodu. Odpalany
# cyklicznie kolidowałby z żywym runner_loop (kill switch jest współdzielony).
EXCLUDE = {"bootstrap_smoke_test.py"}


def discover_tests(directory=APP_DIR):
    """Wszystkie pliki *_smoke_test.py w katalogu, bez wykluczonych."""
    return sorted(t for t in Path(directory).glob(TEST_GLOB) if t.name not in EXCLUDE)


def run_one(test_path):
    """Uruchamia jeden test jako osobny proces. Zwraca {test, ok, output}."""
    test_path = Path(test_path)
    try:
        proc = subprocess.run(
            [sys.executable, str(test_path)],
            cwd=str(test_path.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=PER_TEST_TIMEOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
        return {"test": test_path.name, "ok": proc.returncode == 0,
                "output": (proc.stdout or "") + (proc.stderr or "")}
    except subprocess.TimeoutExpired:
        return {"test": test_path.name, "ok": False, "output": f"TIMEOUT po {PER_TEST_TIMEOUT}s"}


def run_self_check(test_dir=None):
    """Uruchamia wszystkie testy dymne. Drukuje podsumowanie i (dla schedulera)
    rzuca RuntimeError, gdy którykolwiek nie przeszedł. Zwraca podsumowanie,
    gdy wszystko OK."""
    tests = discover_tests(test_dir or APP_DIR)
    results = [run_one(t) for t in tests]
    passed = [r for r in results if r["ok"]]
    failed = [r for r in results if not r["ok"]]

    print(f"Samo-weryfikacja: {len(passed)}/{len(results)} testów przeszło.")
    for r in results:
        print(f"  {'OK  ' if r['ok'] else 'FAIL'} {r['test']}")
    for r in failed:
        print(f"\n----- {r['test']} (wyjście) -----\n{r['output'][-3000:]}")

    if failed:
        raise RuntimeError(
            f"Samo-weryfikacja NIE przeszła: {len(failed)}/{len(results)} testów padło "
            f"({', '.join(r['test'] for r in failed)})."
        )
    return {"total": len(results), "passed": len(passed)}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        run_self_check()
    except RuntimeError as exc:
        print(f"\n{exc}")
        sys.exit(1)
