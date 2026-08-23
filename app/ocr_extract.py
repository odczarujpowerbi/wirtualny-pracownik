"""
OCR — twardy ODCZYT tekstu i liczb ze zrzutu ekranu. Świadomie oddzielony od
oceny wizualnej Oskara ("czy wygląda dobrze"): to dwa różne zadania. Model
wizyjny bywa zawodny na drobnym tekście i cyfrach w Power BI — do sprawdzenia,
czy liczba na raporcie zgadza się ze źródłem, potrzebny jest OCR, nie "wrażenie".

Hierarchia (od najtańszej, lokalnej, do chmurowej):
  1. pytesseract (silnik Tesseract, lokalnie) — jeśli pakiet ORAZ binarka są.
  2. Model wizyjny Anthropic w trybie "przepisz tekst" — jeśli ANTHROPIC_API_KEY.
  3. Brak — available=False z jasnym powodem (fail-closed, nie udajemy odczytu).

Nigdy nie rzuca: brak backendu/pliku to available=False, nie wyjątek.
"""

import base64
import mimetypes
import os
import re
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem kluczy
import model_registry

DEFAULT_LANG = os.environ.get("OCR_LANG", "pol+eng")
_ANTHROPIC_OCR_PROMPT = (
    "Przepisz DOKŁADNIE cały tekst widoczny na obrazie, zachowując liczby, znaki "
    "walut i separatory bez zmian. Nie komentuj, nie interpretuj — sam odczytany tekst."
)


def _result(available, text=None, source=None, detail=""):
    return {"available": available, "text": text, "source": source, "detail": detail}


def _ocr_tesseract(path, lang):
    import pytesseract  # lazy: opcjonalna zależność
    from PIL import Image

    text = pytesseract.image_to_string(Image.open(path), lang=lang)
    return text.strip()


def _ocr_anthropic(path):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    import anthropic  # lazy

    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    image_b64 = base64.standard_b64encode(Path(path).read_bytes()).decode("utf-8")
    client = anthropic.Anthropic()
    _, model = model_registry.resolve("ocr_extract.extract")
    response = client.messages.create(
        model=model,
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                {"type": "text", "text": _ANTHROPIC_OCR_PROMPT},
            ],
        }],
    )
    return response.content[0].text.strip()


def extract_text(image_path, lang=DEFAULT_LANG):
    """Zwraca {available, text, source, detail}. source ∈ {tesseract, anthropic}."""
    path = Path(image_path)
    if not path.is_file():
        return _result(False, None, None, f"Plik obrazu nie istnieje: {image_path}")

    tesseract_error = None
    try:
        return _result(True, _ocr_tesseract(path, lang), "tesseract", "OK")
    except ImportError:
        pass  # brak pytesseract/Pillow — próbujemy chmury
    except Exception as exc:  # noqa: BLE001 — np. brak binarki Tesseract w PATH
        tesseract_error = str(exc)

    try:
        text = _ocr_anthropic(path)
        if text is not None:
            return _result(True, text, "anthropic", "OK (model wizyjny)")
    except Exception:  # noqa: BLE001 — sieć/klucz/model: brak odczytu, nie crash
        pass

    hint = "Zainstaluj Tesseract (+ pytesseract) albo ustaw ANTHROPIC_API_KEY."
    if tesseract_error:
        hint = f"Tesseract obecny, ale zawiódł ({tesseract_error}). " + hint
    return _result(False, None, None, "Brak dostępnego OCR. " + hint)


def contains_number(text, expected, tolerance=0.0):
    """Czy w odczytanym tekście występuje liczba równa expected (z tolerancją).
    Pomocnicze przy walidacji: 'czy raport pokazuje tę wartość co źródło'.
    Obsługuje separatory pl (1 234,50) i en (1,234.50)."""
    if not text:
        return False
    for raw in re.findall(r"-?\d[\d\s.,]*", text):
        cleaned = re.sub(r"\s", "", raw)  # spacje/nbsp/tab = separatory tysiecy
        # Heurystyka: ostatni separator to dziesiętny, wcześniejsze to tysiące.
        cleaned = cleaned.replace(".", "#").replace(",", "#")
        if "#" in cleaned:
            head, _, tail = cleaned.rpartition("#")
            cleaned = head.replace("#", "") + "." + tail
        try:
            if abs(float(cleaned) - float(expected)) <= float(tolerance):
                return True
        except ValueError:
            continue
    return False


if __name__ == "__main__":
    import sys

    print(extract_text(sys.argv[1] if len(sys.argv) > 1 else "runs/screenshots/shot.png"))
