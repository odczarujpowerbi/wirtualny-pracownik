"""
Wspólny kontrakt botów walidujących (bramka jakości, bot_gustaw_bramka.py).
Każdy bot ma tę samą sygnaturę:

    review(task: dict, execution_result: dict, config: dict | None) -> dict

i zwraca werdykt zbudowany przez verdict() poniżej. Trzymamy to w jednym
miejscu, bo używa tego 5 botów — jedna zmiana kształtu werdyktu zamiast pięciu.

verdict ∈ {approved, rejected, skipped}:
  approved  — bot potwierdza, że efekt jest OK z jego perspektywy
  rejected  — bot znalazł problem, który powinien wstrzymać zadanie (blokuje)
  skipped   — bot nie miał czego sprawdzić (np. brak zrzutu ekranu). NIE blokuje
              sam z siebie, ale Gustaw traktuje pominięcie bota OBOWIĄZKOWEGO
              jako brak zgody (fail-closed).
"""

VALID_VERDICTS = ("approved", "rejected", "skipped")


def verdict(bot, decision, confidence, detail, concerns=None):
    if decision not in VALID_VERDICTS:
        raise ValueError(f"Nieznany werdykt '{decision}', dozwolone: {VALID_VERDICTS}")
    return {
        "bot": bot,
        "verdict": decision,
        "confidence": round(float(confidence), 2),
        "detail": detail,
        "concerns": list(concerns or []),
    }
