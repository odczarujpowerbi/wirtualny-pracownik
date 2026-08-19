"""
Szacowanie kosztu wywołania modelu. Naprawia realną dziurę bezpieczeństwa:
task_thinker zwracał cost_usd=0.0 dla Claude Code (subskrypcja), więc dzienny
kill switch kosztowy nigdy nie liczył głównej ścieżki modelu i w praktyce nie
działał.

Subskrypcja Claude Code nie ma ceny per wywołanie, ale POTRZEBUJEMY niezerowej
liczby, żeby ograniczyć WOLUMEN wywołań (kill switch po przekroczeniu dziennego
progu). Dlatego dla claude_code używamy konfigurowalnego szacunku proxy per
wywołanie — to nie jest rachunek, to bezpiecznik wolumenu (jawnie oznaczony).

Dla SDK (płatne per token) liczymy z grubsza po tokenach (≈4 znaki/token) wg
cennika Opus. To szacunek, nie faktura — ma zapobiegać ucieczce kosztów, nie
księgować co do centa.
"""

import os

# Proxy kosztu jednego wywołania Claude Code (subskrypcja). Konfigurowalne env,
# żeby dostroić bezpiecznik wolumenu bez zmiany kodu.
CLAUDE_CODE_PROXY_USD = float(os.environ.get("CLAUDE_CODE_CALL_PROXY_USD", "0.05"))

# Cennik Opus (USD za token) — wejście/wyjście. Szacunek do bezpiecznika, nie faktura.
_OPUS_INPUT_PER_TOKEN = 15.0 / 1_000_000
_OPUS_OUTPUT_PER_TOKEN = 75.0 / 1_000_000
_CHARS_PER_TOKEN = 4


def _tokens(chars):
    return max(0, int(chars)) / _CHARS_PER_TOKEN


def estimate_call(source, input_chars=0, output_chars=0):
    """Szacowany koszt USD jednego wywołania modelu.
      - claude_code  -> stały proxy (bezpiecznik wolumenu subskrypcji)
      - anthropic_sdk -> szacunek po tokenach (cennik Opus)
      - ollama/local/None -> 0.0 (lokalny, bez kosztu API)
    """
    if source == "claude_code":
        return round(CLAUDE_CODE_PROXY_USD, 4)
    if source == "anthropic_sdk":
        cost = _tokens(input_chars) * _OPUS_INPUT_PER_TOKEN + _tokens(output_chars) * _OPUS_OUTPUT_PER_TOKEN
        return round(cost, 4)
    return 0.0


if __name__ == "__main__":
    print("claude_code:", estimate_call("claude_code"))
    print("sdk 2000/600 znaków:", estimate_call("anthropic_sdk", input_chars=2000, output_chars=600))
    print("ollama:", estimate_call("ollama"))
