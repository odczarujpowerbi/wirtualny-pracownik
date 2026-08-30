"""
Bartek — bot-dubler / regresja.

Funkcja: niezależnie POWTARZA to samo zadanie i porównuje wynik z pierwszym
przebiegiem. Wychwytuje niedeterminizm ("działa raz na dwa razy") — coś, czego
pojedynczy przebieg nie widzi. To odpowiednik "testu podobnego bota, który to
robił": drugie, niezależne wykonanie, które musi dać ten sam efekt.

Jak porównuje:
- Jeśli execution_result niesie wywoływalne `rerun` (funkcja bezargumentowa,
  która wykonuje zadanie jeszcze raz), Bartek je uruchamia i porównuje sygnatury
  obu wyników. Rozbieżność = niedeterminizm -> odrzucenie (blokujące wg configu).
- Jeśli zadanie nie daje sposobu na powtórzenie, Bartek nie zgaduje — zwraca
  `skipped` (nie ma czego porównać). To uczciwe: regresji nie da się udać bez
  drugiego przebiegu.

Kontrakt: patrz bot_common.py.
"""

import hashlib
import json

from bot_common import verdict

BOT = "bartek"


def _signature(value):
    """Stabilna sygnatura dowolnego wyniku, do porównania dwóch przebiegów."""
    if value is None:
        return None
    try:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        canonical = repr(value)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def review(task, execution_result, config=None, context=None):
    """context (kesz projektów/etapów/wiedzy, context_cache.py): PRZYJĘTY dla
    jednolitego wywołania z bot_gustaw_bramka.run_gate, ale NIEUŻYWANY — kontrola
    determinizmu jest mechaniczna (porównanie dwóch przebiegów), kontekst
    biznesowy niczego tu nie zmienia."""
    config = config or {}
    rerun = execution_result.get("rerun")

    if not callable(rerun):
        return verdict(
            BOT, "skipped", 0.3,
            "Zadanie nie dostarcza sposobu na powtórzenie (execution_result['rerun']). "
            "Regresji nie da się wykonać bez drugiego przebiegu — pomijam.",
        )

    try:
        second = rerun()
    except Exception as exc:  # noqa: BLE001 — błąd przy powtórce sam w sobie jest sygnałem
        return verdict(
            BOT, "rejected", 0.8,
            f"Powtórzony przebieg zakończył się błędem: {exc}",
            concerns=["Zadanie nie jest powtarzalne — druga próba rzuciła wyjątek."],
        )

    first_sig = execution_result.get("result_signature") or _signature(execution_result.get("output"))
    second_sig = _signature(second)

    if first_sig is not None and first_sig == second_sig:
        return verdict(BOT, "approved", 0.9, "Dwa niezależne przebiegi dały identyczny wynik (brak niedeterminizmu).")

    blocking = config.get("blocking_on_mismatch", True)
    return verdict(
        BOT, "rejected" if blocking else "approved", 0.7,
        "Powtórzony przebieg dał INNY wynik niż pierwszy — możliwy niedeterminizm.",
        concerns=["Rozbieżność między pierwszym a drugim przebiegiem tego samego zadania."],
    )
