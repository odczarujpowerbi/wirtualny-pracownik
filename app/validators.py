"""
Walidatory dla żółtych akcji (PLAN-WDROZENIA.md sekcja 3, SKRYPTY.md
kategoria C). Każdy walidator ma ten sam kontrakt:

    validate(task: dict, execution_result: dict) -> dict z polami:
        approved: bool
        confidence: float (0-1)
        detail: str

Zasada fail-closed: gdy walidator nie ma wystarczających danych do oceny
(np. brak zrzutu ekranu), zwraca approved=False z wyjaśnieniem — NIE pomija
się cicho. Brak dowodu to sygnał do eskalacji, nie automatyczna zgoda.
"""

import os

import env_bootstrap  # noqa: F401  # wczytuje .env / secrets/.env przed odczytem ANTHROPIC_API_KEY


def validator_technical(task, execution_result):
    """Sprawdza podstawową poprawność wyniku wykonania: brak błędu, obecność
    oczekiwanych pól. Deterministyczne, bez AI."""
    if execution_result.get("error"):
        return {
            "validator": "technical",
            "approved": False,
            "confidence": 1.0,
            "detail": f"Wynik zawiera błąd: {execution_result['error']}",
        }

    acceptance_criteria = task.get("acceptance_criteria", [])
    if acceptance_criteria and not execution_result.get("acceptance_notes"):
        return {
            "validator": "technical",
            "approved": False,
            "confidence": 0.6,
            "detail": "Zadanie ma kryteria akceptacji, ale wynik nie odnosi się do nich (`acceptance_notes` puste).",
        }

    return {
        "validator": "technical",
        "approved": True,
        "confidence": 0.9,
        "detail": "Brak błędu, wynik zawiera odniesienie do kryteriów akceptacji.",
    }


def validator_scope(task, execution_result):
    """Sprawdza, czy koszt i zakres mieszczą się w tym, co zadeklarowano
    w zadaniu (PLAN-WDROZENIA.md sekcja 1: max_ai_cost_usd)."""
    max_cost = task.get("max_ai_cost_usd")
    actual_cost = execution_result.get("cost_usd", 0)

    if max_cost is not None and actual_cost > max_cost:
        return {
            "validator": "scope",
            "approved": False,
            "confidence": 1.0,
            "detail": f"Koszt {actual_cost} USD przekracza zadeklarowany limit {max_cost} USD.",
        }

    return {
        "validator": "scope",
        "approved": True,
        "confidence": 0.85,
        "detail": f"Koszt {actual_cost} USD w granicach limitu {max_cost} USD.",
    }


def validator_visual(task, execution_result):
    """Ocena zrzutu ekranu przez model AI (vision_reviewer — SKRYPTY.md
    kategoria C). W tym szkielecie: jeśli brak zrzutu ALBO brak klucza API,
    NIE pomija się po cichu — zwraca approved=False (fail-closed: brak
    dowodu wizualnego to sygnał do eskalacji, nie cicha zgoda)."""
    screenshot_path = execution_result.get("screenshot_path")

    if not screenshot_path:
        return {
            "validator": "visual",
            "approved": False,
            "confidence": 0.3,
            "detail": "Brak zrzutu ekranu do oceny — zadanie wymaga weryfikacji wizualnej, ale nic nie dostarczono.",
        }

    if not os.environ.get("ANTHROPIC_API_KEY"):
        return {
            "validator": "visual",
            "approved": False,
            "confidence": 0.3,
            "detail": "Brak klucza ANTHROPIC_API_KEY — walidator wizualny nie może ocenić zrzutu (do podłączenia na docelowej maszynie).",
        }

    return _call_vision_model(task, screenshot_path)


def _call_vision_model(task, screenshot_path):
    """Realne wywołanie modelu wizyjnego. Wymaga pakietu `anthropic`
    (requirements.txt) i ANTHROPIC_API_KEY w środowisku. Nietestowane w tej
    sesji z prawdziwym kluczem (brak dostępu do niego stąd) — sprawdź na
    docelowej maszynie."""
    import base64
    import mimetypes
    from pathlib import Path

    try:
        import anthropic
    except ImportError:
        return {
            "validator": "visual",
            "approved": False,
            "confidence": 0.3,
            "detail": "Pakiet 'anthropic' niezainstalowany (pip install -r requirements.txt).",
        }

    path = Path(screenshot_path)
    if not path.exists():
        return {
            "validator": "visual",
            "approved": False,
            "confidence": 0.3,
            "detail": f"Plik zrzutu {screenshot_path} nie istnieje.",
        }

    media_type = mimetypes.guess_type(str(path))[0] or "image/png"
    image_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

    prompt = (
        f"Zadanie: {task.get('title')}\n"
        f"Oczekiwany rezultat: {task.get('expected_result')}\n\n"
        "Oceń załączony zrzut ekranu. Czy wygląda poprawnie: brak błędów, "
        "brak elementów wychodzących poza obszar, brak nieoczekiwanych "
        "komunikatów? Odpowiedz DOKŁADNIE w formacie:\n"
        "APPROVED: tak|nie\n"
        "UZASADNIENIE: <1-2 zdania>"
    )

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model="claude-sonnet-4-5",
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        )
        text = response.content[0].text
    except Exception as e:  # sieć/klucz/model — traktujemy jako fail-closed, nie crash runnera
        return {
            "validator": "visual",
            "approved": False,
            "confidence": 0.3,
            "detail": f"Błąd wywołania modelu wizyjnego: {e}",
        }

    approved = "approved: tak" in text.lower()
    return {"validator": "visual", "approved": approved, "confidence": 0.8, "detail": text.strip()}


ALL_VALIDATORS = {
    "technical": validator_technical,
    "scope": validator_scope,
    "visual": validator_visual,
}
