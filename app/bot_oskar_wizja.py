"""
Oskar — kontrola organoleptyczna (wizualna).

Funkcja: patrzy na ZRZUT EKRANU efektu i ocenia go modelem wizyjnym — tak jak
człowiek, który rzuca okiem: czy nie ma błędów, uciętych wykresów, pustych
sekcji, komunikatów o błędzie, elementów wychodzących poza obszar. To warstwa
"model lokalny weryfikuje, robi screeny, weryfikuje".

Hierarchia modelu wizyjnego:
1. Lokalny model wizyjny przez Ollamę (OLLAMA_VISION_MODEL) — jeśli dostępny.
2. Fallback: model wizyjny Anthropic (ANTHROPIC_API_KEY).

Brak zrzutu = `skipped` (nie ma czego oglądać — nie blokuje sam z siebie, ale
zostawia to jako uwagę). Zrzut + model, który ocenia negatywnie = `rejected`.
Zrzut bez żadnego dostępnego modelu = `skipped` z jawną uwagą, że nie dało się
zweryfikować wizualnie.

Kontrakt: patrz bot_common.py.
"""

import base64
import json
import mimetypes
import os
import urllib.error
import urllib.request
from pathlib import Path

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem kluczy
from bot_common import verdict

BOT = "oskar"

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_VISION_MODEL = os.environ.get("OLLAMA_VISION_MODEL", "llama3.2-vision")
OLLAMA_TIMEOUT_SECONDS = 60


def _build_prompt(task):
    return (
        f"Zadanie: {task.get('title')}\n"
        f"Oczekiwany rezultat: {task.get('expected_result')}\n\n"
        "Oceń załączony zrzut ekranu efektu tego zadania. Czy wygląda poprawnie: "
        "brak komunikatów o błędzie, brak uciętych/wychodzących poza obszar elementów, "
        "brak pustych sekcji i placeholderów, całość spójna z oczekiwanym rezultatem? "
        "Odpowiedz DOKŁADNIE w formacie:\n"
        "OCENA: ok|zle\n"
        "UZASADNIENIE: <1-2 zdania>"
    )


def _ask_ollama_vision(prompt, image_b64):
    payload = json.dumps(
        {"model": OLLAMA_VISION_MODEL, "prompt": prompt, "images": [image_b64], "stream": False}
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate", data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    return (result.get("response") or "").strip() or None


def _ask_anthropic_vision(prompt, image_b64, media_type):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        return response.content[0].text.strip()
    except Exception:  # noqa: BLE001 — sieć/klucz/model: brak oceny, nie crash
        return None


def _interpret(answer_text):
    """Zwraca True (ok) / False (źle) na podstawie odpowiedzi modelu."""
    low = answer_text.lower()
    if "ocena: ok" in low or "approved: tak" in low:
        return True
    if "ocena: zle" in low or "ocena: złe" in low or "approved: nie" in low:
        return False
    # Brak jednoznacznego markera — fail-closed: traktuj jako niepotwierdzone (źle).
    return False


def review(task, execution_result, config=None):
    config = config or {}
    screenshot_path = execution_result.get("screenshot_path")

    if not screenshot_path:
        return verdict(
            BOT, "skipped", 0.3,
            "Brak zrzutu ekranu efektu — nie ma czego oceniać wizualnie.",
            concerns=["Efekt bez zrzutu ekranu nie przeszedł kontroli wizualnej."],
        )

    path = Path(screenshot_path)
    if not path.is_file():
        return verdict(BOT, "skipped", 0.3, f"Podany zrzut ekranu nie istnieje: {screenshot_path}",
                       concerns=["Brakujący plik zrzutu ekranu."])

    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    image_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    prompt = _build_prompt(task)

    answer = _ask_ollama_vision(prompt, image_b64)
    source = "ollama"
    if answer is None:
        answer = _ask_anthropic_vision(prompt, image_b64, media_type)
        source = "anthropic"

    if answer is None:
        return verdict(
            BOT, "skipped", 0.3,
            "Jest zrzut ekranu, ale żaden model wizyjny nie jest dostępny (Ollama/Anthropic) — nie zweryfikowano.",
            concerns=["Nie udało się zweryfikować wizualnie efektu (brak modelu)."],
        )

    looks_ok = _interpret(answer)
    if looks_ok:
        return verdict(BOT, "approved", 0.8, f"[{source}] {answer}")

    blocking = config.get("blocking_on_bad_visual", True)
    return verdict(
        BOT, "rejected" if blocking else "approved", 0.8, f"[{source}] {answer}",
        concerns=["Model wizyjny ocenił zrzut ekranu jako niepoprawny."],
    )
