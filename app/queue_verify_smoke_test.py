"""
Test dymny queue_verify.py — diagnozy "dodałem zadanie, a bot go nie widzi".
Zero sieci: klienci Projectly to atrapy.

Użycie:
    python queue_verify_smoke_test.py
"""

import sys

import queue_verify


class _Klient:
    def __init__(self, projekty, zadania):
        self._projekty = projekty
        self._zadania = zadania

    def polled_project_names(self):
        return list(self._projekty)

    def get_new_tasks(self):
        return list(self._zadania)

    def project_name(self, project_id):
        return {"P1": "Administracyjne", "P2": "LDIT"}.get(project_id)


class _KlientZBledem(_Klient):
    def get_new_tasks(self):
        raise ConnectionError("brak tokenu roli")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    klienci = {
        "dev": _Klient(["Administracyjne", "LDIT"],
                       [{"title": "Zrób raport", "status": "todo", "project_id": "P1"}]),
        "marketing": _Klient(["Administracyjne"], []),
        "checker": _KlientZBledem([], []),
    }
    wynik = queue_verify.zbadaj(roles=["dev", "marketing", "checker"],
                                client_factory=lambda rola: klienci[rola])
    po_roli = {r["role"]: r for r in wynik["role"]}

    checks.append(("kolejka roli z zadaniem: 1 pozycja, z nazwą projektu",
                   len(po_roli["dev"]["kolejka"]) == 1
                   and po_roli["dev"]["kolejka"][0]["projekt"] == "Administracyjne"))

    checks.append(("rola bez zadań: kolejka pusta, BEZ błędu",
                   po_roli["marketing"]["kolejka"] == [] and po_roli["marketing"]["blad"] is None))

    # Error case: jedna rola bez tokenu nie może przerwać diagnozy pozostałych.
    checks.append(("rola z błędem: raport zawiera treść błędu, pozostałe role zbadane",
                   po_roli["checker"]["blad"] is not None and len(wynik["role"]) == 3))

    # Luka uprawnień: LDIT widzi tylko dev — to jest istota tej diagnozy.
    luki = {l["projekt"]: l for l in wynik["luki"]}
    checks.append(("luka uprawnień: projekt widoczny tylko dla jednej roli jest ZGŁOSZONY",
                   "LDIT" in luki and luki["LDIT"]["widza"] == ["dev"]
                   and set(luki["LDIT"]["nie_widza"]) == {"marketing", "checker"}))

    checks.append(("projekt widoczny dla wszystkich, które go mają, ale nie dla roli z błędem -> też luka",
                   "Administracyjne" in luki and luki["Administracyjne"]["nie_widza"] == ["checker"]))

    # Brak luk, gdy każda rola widzi to samo.
    rowne = {rola: _Klient(["Administracyjne"], []) for rola in ("dev", "marketing")}
    wynik_rowny = queue_verify.zbadaj(roles=["dev", "marketing"],
                                      client_factory=lambda rola: rowne[rola])
    checks.append(("wszystkie role widzą te same projekty -> zero luk",
                   wynik_rowny["luki"] == []))

    queue_verify.wypisz(wynik)  # nie może się wywrócić na roli z błędem
    checks.append(("wypisz() radzi sobie z rolą, która zwróciła błąd", True))

    print("\n--- Wynik testu dymnego queue_verify ---")
    all_passed = True
    for opis, ok in checks:
        print(("✅ " if ok else "❌ ") + opis)
        all_passed = all_passed and ok
    return all_passed


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
