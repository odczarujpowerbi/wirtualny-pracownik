"""
Test dymny model_registry — rejestru modeli i tabeli tier dla całego projektu.
Bez sieci — testuje tylko odczyt config/models.yaml i config/model_tiers.yaml.

Kluczowe przypadki: fail-closed dla nieznanego callera (-> tier "high") i dla
nieznanej roli (-> "opus_5"), bo to jedyne miejsce, gdzie błąd w konfiguracji
mógłby po cichu ustawić drogi model na wszystko albo tani model na osąd.

Użycie:
    python model_registry_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import model_registry


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    checks.append(("Znany caller z tabeli -> tier zgodny z config/model_tiers.yaml",
                   model_registry.tier_for_caller("web_answer.answer") == "low"
                   and model_registry.tier_for_caller("task_thinker.think") == "high"))
    checks.append(("Agent sterujący (task_thinker.think/task_decomposer.decide/output_decider.decide) "
                   "-> tier 'high' -> rola opus_5 (cofnięte z Fable 5 29.08.2026: $200 spalone przez "
                   "repo_auto_improver na Fable 5 bez widoczności kosztu w Projectly)",
                   model_registry.tier_for_caller("task_decomposer.decide") == "high"
                   and model_registry.tier_for_caller("output_decider.decide") == "high"
                   and model_registry.tier_for_caller("repo_auto_improver.napraw_zadanie") == "high"
                   and model_registry.role_for_tier("high") == "opus_5"
                   and model_registry.model_id("opus_5") == "claude-opus-5"))
    checks.append(("Nieznany caller -> tier 'high' (fail-closed)",
                   model_registry.tier_for_caller("cos.czego.nie.ma") == "high"))

    checks.append(("Znany tier -> rola z 'poziomy'",
                   model_registry.role_for_tier("high") == "opus_5"
                   and model_registry.role_for_tier("low") == "sonnet_4_6"))
    checks.append(("Nieznany tier -> rola domyślna 'opus_5' (fail-closed)",
                   model_registry.role_for_tier("sredni") == "opus_5"))

    checks.append(("Znana rola -> właściwe ID modelu",
                   model_registry.model_id("opus_5") == "claude-opus-5"
                   and model_registry.model_id("sonnet_4_6") == "claude-sonnet-4-6"))
    checks.append(("Nieznana rola -> ID roli domyślnej, nie wyjątek",
                   model_registry.model_id("nieznana_rola") == model_registry.model_id("opus_5")))

    checks.append(("Cennik znanej roli zwraca dwie liczby (input, output)",
                   model_registry.pricing("sonnet_4_6") == (3.0, 15.0)))
    checks.append(("Cennik nieznanej roli spada do roli domyślnej",
                   model_registry.pricing("nieznana_rola") == model_registry.pricing("opus_5")))

    checks.append(("resolve() dla wykonawcy daje (sonnet_4_6, claude-sonnet-4-6)",
                   model_registry.resolve("poprawka_materialu.popraw") == ("sonnet_4_6", "claude-sonnet-4-6")))
    checks.append(("resolve() dla oceny wizualnej (Oskar) daje wysoki poziom",
                   model_registry.resolve("bot_oskar_wizja.review")[0] == "opus_5"))

    with tempfile.TemporaryDirectory() as tmp:
        brak = Path(tmp) / "nie_ma.yaml"
        checks.append(("Brak pliku models.yaml -> pusty rejestr, nie wyjątek",
                       model_registry.load_models(brak) == {}))
        checks.append(("Brak pliku model_tiers.yaml -> tier domyślny, nie wyjątek",
                       model_registry.tier_for_caller("cokolwiek", brak) == "high"))
        checks.append(("Brak pliku models.yaml -> model_id nieznanej roli nie rzuca",
                       model_registry.model_id("opus_5", path=brak) is None))

    print("\n--- Wynik testu dymnego model_registry ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
