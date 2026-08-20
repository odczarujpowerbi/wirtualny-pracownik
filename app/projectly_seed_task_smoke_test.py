"""
Test dymny projectly_seed_task — zakładania zadań w Projectly. CELOWO BEZ SIECI:
klient jest atrapą, więc test nie dotyka żywego konta (żaden test regresji nie
może tworzyć zadań u klienta).

Pokrywa: podgląd bez zapisu (domyślny, bezpieczny tryb), realne utworzenie po
potwierdzeniu, nieznany projekt oraz to, że zadanie ląduje w koncie AI maszyny.

Użycie:
    python projectly_seed_task_smoke_test.py
"""

import sys

import projectly_seed_task


class _AtrapaKlienta:
    def __init__(self, projekty=None):
        self._projects = projekty if projekty is not None else [
            {"id": "p1", "name": "Administracyjne", "status": "active"},
            {"id": "p2", "name": "DEV - Anava", "status": "active"},
        ]
        self.utworzone = []

    def _ensure_directory(self):
        pass

    def _project_id_by_name(self, nazwa):
        for p in self._projects:
            if p["name"].lower() == str(nazwa).lower():
                return p["id"]
        return None

    def create_task(self, title, description, assigned_to, project_id=None, **kw):
        self.utworzone.append({"title": title, "description": description,
                               "assigned_to": assigned_to, "project_id": project_id})
        return "TASK-123"


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    klient = _AtrapaKlienta()
    podglad = projectly_seed_task.zaloz_zadanie("Kurs EUR", "https://api.nbp.pl/x", "Administracyjne",
                                                client=klient, wykonaj=False)
    checks.append(("Domyślnie tylko podgląd — nic nie trafia do Projectly",
                   podglad["utworzone"] is False and klient.utworzone == []))
    checks.append(("Podgląd mówi wprost, że nie zapisuje", "PODGLĄD" in podglad["detal"]))

    utworzone = projectly_seed_task.zaloz_zadanie("Kurs EUR", "https://api.nbp.pl/x", "Administracyjne",
                                                  client=klient, wykonaj=True)
    checks.append(("Z potwierdzeniem zadanie jest tworzone",
                   utworzone["utworzone"] is True and utworzone["task_id"] == "TASK-123"))
    checks.append(("Zadanie trafia do właściwego projektu", klient.utworzone[0]["project_id"] == "p1"))
    checks.append(("Domyślnie przypisane do konta AI maszyny (alias 'bot')",
                   klient.utworzone[0]["assigned_to"] == "bot"))
    checks.append(("Opis (ze źródłem) jest przekazywany",
                   klient.utworzone[0]["description"] == "https://api.nbp.pl/x"))

    zly = projectly_seed_task.zaloz_zadanie("X", "", "Nie ma takiego", client=klient, wykonaj=True)
    checks.append(("Nieznany projekt -> brak zapisu i lista aktywnych w komunikacie",
                   zly["utworzone"] is False and "Administracyjne" in zly["detal"]))
    checks.append(("Nieznany projekt nie tworzy zadania mimo potwierdzenia", len(klient.utworzone) == 1))

    print("\n--- Wynik testu dymnego projectly_seed_task ---")
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
