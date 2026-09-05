"""
Test dymny host_policy.py. Zero sieci: sprawdza samą regułę, kto gdzie może wejść.

Uzycie:
    python host_policy_smoke_test.py
"""

import sys

import host_policy

WSZYSTKO = [host_policy.WSZYSTKIE_DOMENY]
WASKA = ["api.nbp.pl", "clickless.pl"]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. Allowlista "*": kazda normalna witryna (decyzja wlasciciela 05.09.2026).
    checks.append(("'*': strona klienta przechodzi (realny przypadek ldit.pl)",
                   host_policy.host_dozwolony("https://ldit.pl/dofinansowania", WSZYSTKO)))
    checks.append(("'*': dowolna nieznana witryna przechodzi",
                   host_policy.host_dozwolony("https://cokolwiek.example/x", WSZYSTKO)))

    # 2. Twarde granice obowiazuja TAKZE przy "*".
    checks.append(("'*': darknet .onion zablokowany",
                   not host_policy.host_dozwolony("https://sklep.onion/x", WSZYSTKO)))
    checks.append(("'*': darknet .i2p zablokowany",
                   not host_policy.host_dozwolony("https://cos.i2p/x", WSZYSTKO)))
    checks.append(("'*': localhost zablokowany (panel tej maszyny, nie witryna)",
                   not host_policy.host_dozwolony("https://localhost:8787/", WSZYSTKO)))
    checks.append(("'*': petla zwrotna 127.0.0.1 zablokowana",
                   not host_policy.host_dozwolony("https://127.0.0.1:11434/api", WSZYSTKO)))
    checks.append(("'*': siec prywatna 192.168.x zablokowana",
                   not host_policy.host_dozwolony("https://192.168.1.10/panel", WSZYSTKO)))
    checks.append(("'*': siec prywatna 10.x zablokowana",
                   not host_policy.host_dozwolony("https://10.0.0.5/", WSZYSTKO)))

    # 3. Powod blokady jest nazwany (trafia do notatki dla czlowieka).
    checks.append(("Powod blokady darknetu nazwany wprost",
                   "darknet" in (host_policy.powod_blokady("https://x.onion/") or "")))
    checks.append(("Powod blokady adresu wewnetrznego nazwany wprost",
                   "wewn" in (host_policy.powod_blokady("https://10.0.0.5/") or "")))
    checks.append(("Zwykly adres nie ma powodu blokady",
                   host_policy.powod_blokady("https://ldit.pl/") is None))

    # 4. Waska allowlista dziala jak dotad (narzedzia, ktore jej nie otwieraja:
    #    mailerlite_report, sharepoint_upload, sharepoint_read).
    checks.append(("Waska lista: host z listy przechodzi",
                   host_policy.host_dozwolony("https://api.nbp.pl/api/x", WASKA)))
    checks.append(("Waska lista: subdomena przechodzi",
                   host_policy.host_dozwolony("https://www.clickless.pl/oferta", WASKA)))
    checks.append(("Waska lista: host spoza listy odrzucony",
                   not host_policy.host_dozwolony("https://ldit.pl/", WASKA)))
    checks.append(("Waska lista: sam sufiks NIE wystarcza (podszywanie sie)",
                   not host_policy.host_dozwolony("https://api.nbp.pl.atakujacy.example/x", WASKA)))

    # 5. Fail-closed bez zmian: pusta allowlista niczego nie przepuszcza.
    checks.append(("Pusta allowlista -> odmowa (fail-closed)",
                   not host_policy.host_dozwolony("https://ldit.pl/", [])))
    checks.append(("Adres bez hosta -> odmowa", not host_policy.host_dozwolony("nie-adres", WSZYSTKO)))

    # 6. wszystkie_dozwolone: rozpoznanie polityki (do komunikatow dla czlowieka).
    checks.append(("wszystkie_dozwolone rozpoznaje '*'", host_policy.wszystkie_dozwolone(WSZYSTKO)))
    checks.append(("wszystkie_dozwolone: waska lista to nie '*'",
                   not host_policy.wszystkie_dozwolone(WASKA)))

    print("\n--- Wynik testu dymnego host_policy ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedl.")
        sys.exit(1)
    print("\nWszystkie testy przeszly.")


if __name__ == "__main__":
    run()
