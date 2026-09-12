"""
Test dymny connectors_manifest.py. Zero sieci: klient Projectly to atrapa.

Najwazniejsza asercja: w manifescie NIE MA zadnej wartosci sekretu. To jest
warunek calej konstrukcji (klucze zostaja na maszynie, w Projectly widac tylko
status) — gdyby kiedys ktos dopisal wartosc do manifestu, ten test ma zapiszczec.

Uzycie:
    python connectors_manifest_smoke_test.py
"""

import os
import sys

import connectors_manifest

SEKRET_TESTOWY = "sekretna-wartosc-ktora-nie-moze-wyciec"


class _Klient:
    def __init__(self):
        self.wyslane = None

    def report_connectors(self, connectors):
        self.wyslane = connectors
        return {"reported": len(connectors)}


class _KlientPadajacy:
    def report_connectors(self, connectors):
        raise RuntimeError("Projectly nieosiagalne")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    stary = os.environ.get("MAILERLITE_API_KEY")
    os.environ["MAILERLITE_API_KEY"] = SEKRET_TESTOWY

    try:
        manifest = connectors_manifest.zbuduj()

        checks.append(("Manifest wymienia wszystkie znane polaczenia",
                       len(manifest) == len(connectors_manifest.POLACZENIA)))
        checks.append(("Kazde polaczenie ma klucz, nazwe i status",
                       all(p.get("key") and p.get("name") and p.get("status") for p in manifest)))

        # SEDNO: zadna wartosc sekretu nie moze znalezc sie w manifescie.
        jako_tekst = str(manifest)
        checks.append(("W manifescie NIE MA wartosci sekretu", SEKRET_TESTOWY not in jako_tekst))

        mailerlite = next(p for p in manifest if p["key"] == "mailerlite")
        checks.append(("Ustawiony klucz -> status ok", mailerlite["status"] == "ok"))

        os.environ.pop("MAILERLITE_API_KEY")
        bez_klucza = next(p for p in connectors_manifest.zbuduj() if p["key"] == "mailerlite")
        checks.append(("Brak klucza -> status brak", bez_klucza["status"] == "brak"))
        checks.append(("Brak klucza -> notatka mowi, ktorej zmiennej brakuje",
                       "MAILERLITE_API_KEY" in bez_klucza["statusNote"]))

        # Wysylka do Projectly.
        klient = _Klient()
        wynik = connectors_manifest.zglos(klient)
        checks.append(("Manifest wyslany do Projectly", wynik["wyslane"] is True))
        checks.append(("Do Projectly poszedl komplet polaczen",
                       klient.wyslane is not None and len(klient.wyslane) == len(manifest)))

        # Error case: Projectly nieosiagalne -> bez wyjatku, z powodem.
        wynik_blad = connectors_manifest.zglos(_KlientPadajacy())
        checks.append(("Blad Projectly: bez wyjatku, wyslane=False i powod",
                       wynik_blad["wyslane"] is False and wynik_blad["powod"] != ""))
    finally:
        if stary is None:
            os.environ.pop("MAILERLITE_API_KEY", None)
        else:
            os.environ["MAILERLITE_API_KEY"] = stary

    print("\n--- Wynik testu dymnego connectors_manifest ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'OK  ' if passed else 'BLAD'} {name}")
        all_passed = all_passed and passed

    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedl.")
        sys.exit(1)
    print("\nWszystkie testy przeszly.")


if __name__ == "__main__":
    run()
