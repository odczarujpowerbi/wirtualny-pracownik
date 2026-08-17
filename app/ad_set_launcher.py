"""
Uruchamia nowy testowy zestaw reklam (Meta/TikTok) z wariantem z
ad_copy_generator.py, w ramach budżetu testowego (PLAN-WDROZENIA.md
sekcja 20). To STUB — prawdziwe wywołanie Meta Marketing API / TikTok
Marketing API nie jest jeszcze napisane (SKRYPTY.md kategoria G:
`meta_ads_api_client.py`, `tiktok_ads_api_client.py` też nie napisane).

Bramka bounded_red DZIAŁA już teraz i jest przetestowana — to jest
"prawdziwa" część tego modułu. Dopóki `bounded_red` w approval_policy.yaml
jest puste (zalecany stan startowy), każde wywołanie i tak trafi do
zwykłego czerwonego, niezależnie od tego, co ten stub zwróci.
"""

from bounded_red_executor import check_bounded_red


def launch_test_variant(variant, platform, daily_budget, concurrent_variants, policy=None):
    """variant: jeden wariant z ad_copy_generator.py.
    Zwraca dict z kluczem 'launched' (bool) i 'detail'."""
    allowed, detail = check_bounded_red(
        "ad_test_launch",
        {"daily_budget_per_variant": daily_budget, "concurrent_variants": concurrent_variants},
        policy,
    )

    if not allowed:
        return {"launched": False, "detail": detail, "requires_human": True}

    return _call_ads_api(variant, platform, daily_budget)


def _call_ads_api(variant, platform, daily_budget):
    raise NotImplementedError(
        f"Prawdziwe {platform} Marketing API nie jest jeszcze podłączone. "
        "Napisz meta_ads_api_client.py / tiktok_ads_api_client.py (SKRYPTY.md kategoria G) "
        "i podłącz tutaj, gdy będą dostępne dane uwierzytelniające."
    )


if __name__ == "__main__":
    # Bez wpisów w bounded_red (zalecany stan startowy) — zawsze wymaga człowieka,
    # nawet dla drobnego testu. To oczekiwane i bezpieczne.
    result = launch_test_variant(
        {"headline": "przykład"}, "meta", daily_budget=20, concurrent_variants=3
    )
    print(result)
