"""
Wyłącznik awaryjny (PLAN-WDROZENIA.md sekcja 17). Jeden globalny plik-flaga,
sprawdzany na starcie każdej pętli runnera i przez workery. Ostatnia linia
obrony, nie zamiennik dla risk_classifier/validator_pool.
"""

from pathlib import Path

STOP_FLAG_PATH = Path(__file__).parent / "runs" / "STOP.flag"


def is_active():
    return STOP_FLAG_PATH.exists()


def activate(reason=""):
    STOP_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
    STOP_FLAG_PATH.write_text(reason or "Zatrzymano ręcznie.", encoding="utf-8")


def deactivate():
    STOP_FLAG_PATH.unlink(missing_ok=True)


def reason():
    if STOP_FLAG_PATH.exists():
        return STOP_FLAG_PATH.read_text(encoding="utf-8")
    return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        activate(" ".join(sys.argv[2:]) or "Zatrzymano z CLI.")
        print("Kill switch aktywowany.")
    elif len(sys.argv) > 1 and sys.argv[1] == "resume":
        deactivate()
        print("Kill switch zdjęty.")
    else:
        print("Aktywny:", is_active(), "-", reason())
