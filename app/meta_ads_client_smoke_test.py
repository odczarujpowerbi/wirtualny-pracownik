"""
Test dymny meta_ads_client. Sprawdza logike konfiguracji bez sieci: from_env,
normalizacje act_, walidacje braku danych. Nie dotyka Graph API.

Uzycie: python meta_ads_client_smoke_test.py
"""

import os
import sys

import meta_ads_client as meta


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    saved = {k: os.environ.pop(k, None) for k in ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID")}
    try:
        checks.append(("from_env: brak danych -> None", meta.MetaAdsClient.from_env() is None))

        c1 = meta.MetaAdsClient("tok", "123456")
        checks.append(("konstruktor: dokleja prefiks act_", c1.ad_account_id == "act_123456"))

        c2 = meta.MetaAdsClient("tok", "act_999")
        checks.append(("konstruktor: nie dubluje act_", c2.ad_account_id == "act_999"))

        try:
            meta.MetaAdsClient("", "act_1")
            raised = False
        except meta.MetaAdsError:
            raised = True
        checks.append(("konstruktor: pusty token -> MetaAdsError", raised))

        os.environ["META_ACCESS_TOKEN"] = "tok"
        os.environ["META_AD_ACCOUNT_ID"] = "act_1"
        checks.append(("from_env: dane obecne -> klient", meta.MetaAdsClient.from_env() is not None))

        v = meta.verify.__doc__ is not None  # verify istnieje i ma kontrakt
        checks.append(("verify: funkcja dostepna", v))
    finally:
        for k in ("META_ACCESS_TOKEN", "META_AD_ACCOUNT_ID"):
            os.environ.pop(k, None)
            if saved.get(k) is not None:
                os.environ[k] = saved[k]

    print("\n--- Wynik testu dymnego meta_ads_client ---")
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
