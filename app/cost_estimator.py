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
cennika modelu z `model_registry.pricing(role)` — jedno źródło prawdy dla całego
projektu (config/models.yaml), nie zaszyte tu stałe. Naprawia realny błąd:
wcześniejsze stałe Opusa ($15/$75 za milion) były 3× wyższe niż prawdziwa cena
Opusa 5/4.8 ($5/$25) — koszt SDK był systematycznie zawyżany. To wciąż
szacunek, nie faktura — ma zapobiegać ucieczce kosztów, nie księgować co do centa.
"""

import os

import model_registry

# Proxy kosztu jednego wywołania Claude Code (subskrypcja). Konfigurowalne env,
# żeby dostroić bezpiecznik wolumenu bez zmiany kodu.
CLAUDE_CODE_PROXY_USD = float(os.environ.get("CLAUDE_CODE_CALL_PROXY_USD", "0.05"))

_CHARS_PER_TOKEN = 4


def _tokens(chars):
    return max(0, int(chars)) / _CHARS_PER_TOKEN


def estimate_call(source, input_chars=0, output_chars=0, role=None):
    """Szacowany koszt USD jednego wywołania modelu.
      - claude_code  -> stały proxy (bezpiecznik wolumenu subskrypcji, niezależny
        od modelu — Claude Code jest rozliczany przez subskrypcję)
      - anthropic_sdk -> szacunek po tokenach wg cennika roli (`role`, np. "opus_5"
        albo "sonnet_4_6" — patrz model_registry.py). Brak `role` = konserwatywny
        domyślny szacunek (rola domyślna rejestru, dziś Opus).
      - ollama/local/None -> 0.0 (lokalny, bez kosztu API)
    """
    if source == "claude_code":
        return round(CLAUDE_CODE_PROXY_USD, 4)
    if source == "anthropic_sdk":
        input_per_million, output_per_million = model_registry.pricing(role or model_registry.DEFAULT_ROLE)
        cost = (_tokens(input_chars) * input_per_million / 1_000_000
                + _tokens(output_chars) * output_per_million / 1_000_000)
        return round(cost, 4)
    return 0.0


if __name__ == "__main__":
    print("claude_code:", estimate_call("claude_code"))
    print("sdk 2000/600 znaków (domyślna rola):", estimate_call("anthropic_sdk", input_chars=2000, output_chars=600))
    print("sdk 2000/600 znaków (sonnet_4_6):",
          estimate_call("anthropic_sdk", input_chars=2000, output_chars=600, role="sonnet_4_6"))
    print("ollama:", estimate_call("ollama"))
