"""
Skanuje tekst/logi pod kątem sekretów przed zapisem/synchronizacją
(PLAN-WDROZENIA.md dokumentacja bazowa 9.3, SKRYPTY.md kategoria K).
Maskuje pola password/token/api_key/authorization/cookie i wykrywa
typowe wzorce kluczy (żeby złapać też wartości bez opisowego klucza obok).
"""

import re

FIELD_PATTERN = re.compile(
    r"(password|token|api[_-]?key|authorization|cookie|secret)\s*[:=]\s*\S+",
    re.IGNORECASE,
)

# Typowe kształty kluczy dostawców, żeby złapać sekret nawet bez opisowej etykiety obok.
KEY_SHAPE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),  # klucze w stylu Anthropic/OpenAI
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),  # klucze Google
]


def scan_and_mask(text):
    """Zwraca (masked_text, found: bool). Nigdy nie zwraca oryginalnej
    wartości sekretu — tylko informację, że coś zamaskowano."""
    found = False

    def _mask_field(match):
        nonlocal found
        found = True
        key = match.group(1)
        return f"{key}: ***MASKED***"

    masked = FIELD_PATTERN.sub(_mask_field, text)

    for pattern in KEY_SHAPE_PATTERNS:
        if pattern.search(masked):
            found = True
            masked = pattern.sub("***MASKED***", masked)

    return masked, found


if __name__ == "__main__":
    sample = "api_key: sk-abcdefghijklmnopqrstuvwxyz123456\npassword=hunter2\nzwykły tekst bez sekretów"
    masked, found = scan_and_mask(sample)
    print("found:", found)
    print(masked)
