"""
Wykonuje czerwoną akcję bez pytania, TYLKO jeśli mieści się w jawnie
zdefiniowanej granicy liczbowej w approval_policy.yaml (bounded autonomy,
PLAN-WDROZENIA.md sekcja 3). Brak wpisu w bounded_red = zwykłe czerwone,
zawsze do człowieka. Granice ustawia człowiek, ten moduł nigdy ich nie
rozszerza ani nie zgaduje.

Obsługuje dwa kształty granic (rozszerzalne o kolejne w miarę potrzeby):
  - max_percent_change: zmiana istniejącej wartości o maks. X% (np. budżet
    kampanii, PLAN-WDROZENIA.md sekcja 3).
  - max_daily_budget_per_variant + max_concurrent_variants: uruchamianie
    NOWYCH, ograniczonych testów (np. warianty reklam — sekcja 20 planu),
    gdzie granica dotyczy nowej rzeczy, nie zmiany istniejącej.
"""

from risk_classifier import bounded_red_limit


def check_bounded_red(action_type, proposed_change, policy=None):
    """proposed_change zależy od kształtu granicy — patrz docstring modułu.
    Zwraca (allowed: bool, detail: str)."""
    limit = bounded_red_limit(action_type, policy)

    if limit is None:
        return False, "Brak zdefiniowanej granicy dla tego typu akcji — zwykłe czerwone, do człowieka."

    if "max_percent_change" in limit:
        return _check_percent_change(limit, proposed_change)

    if "max_daily_budget_per_variant" in limit:
        return _check_test_launch(limit, proposed_change)

    return False, "Format granicy nieznany — bezpieczniej potraktować jako zwykłe czerwone."


def _check_percent_change(limit, proposed_change):
    max_percent = limit["max_percent_change"]
    change = proposed_change.get("percent_change")
    if change is None:
        return False, "Nie podano wielkości zmiany do porównania z granicą."
    if abs(change) <= max_percent:
        return True, f"Zmiana {change}% mieści się w granicy ±{max_percent}%."
    return False, f"Zmiana {change}% przekracza granicę ±{max_percent}% — wraca do zwykłego czerwonego."


def _check_test_launch(limit, proposed_change):
    max_budget = limit["max_daily_budget_per_variant"]
    max_concurrent = limit.get("max_concurrent_variants")

    daily_budget = proposed_change.get("daily_budget_per_variant")
    concurrent = proposed_change.get("concurrent_variants")

    if daily_budget is None or concurrent is None:
        return False, "Nie podano budżetu dziennego lub liczby równoległych wariantów do porównania z granicą."

    if daily_budget > max_budget:
        return False, f"Budżet testowy {daily_budget} przekracza granicę {max_budget} na wariant — zwykłe czerwone."

    if max_concurrent is not None and concurrent > max_concurrent:
        return False, f"{concurrent} równoległych wariantów przekracza granicę {max_concurrent} — zwykłe czerwone."

    return True, f"Budżet {daily_budget}/wariant i {concurrent} wariantów mieszczą się w granicach."


if __name__ == "__main__":
    # Bez wpisów w bounded_red (domyślna, zalecana konfiguracja startowa) —
    # zawsze powinno wracać False.
    print(check_bounded_red("meta_ads_budget_change", {"percent_change": 5}))
    print(check_bounded_red("ad_test_launch", {"daily_budget_per_variant": 20, "concurrent_variants": 3}))
