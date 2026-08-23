"""
Zakładanie zadania w REALNYM Projectly z linii poleceń — druga strona pętli:
`runner_loop.py` zadania odbiera, ten skrypt je wystawia. Służy do prowadzenia
kontrolowanych przebiegów na żywym koncie (agent dostaje zadanie tą samą drogą,
co od człowieka) i do zakładania zadań przez samego agenta.

Domyślnie zadanie trafia do konta AI tej maszyny (rola z runs/role.json przez
config/projectly.yaml), bo to ono jest pollowane przez runnera.

Bezpieczeństwo: skrypt PISZE do żywego Projectly, więc bez `--yes` tylko
pokazuje, co by zrobił (podgląd), zamiast tworzyć zadanie po cichu.

Użycie:
    python projectly_seed_task.py --projekt "Administracyjne" --tytul "..." --opis "..." --yes
    python projectly_seed_task.py --projekt "Administracyjne" --tytul "..."          # podgląd
    python projectly_seed_task.py --lista-projektow
"""

import argparse
import sys

import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows) + wczytanie secrets/.env
from projectly_client import ProjectlyClient, get_client


def _real_client():
    """Realny klient albo czytelny błąd — seedowanie mocka nie miałoby sensu."""
    client = get_client()
    if not isinstance(client, ProjectlyClient):
        raise SystemExit("Brak PROJECTLY_API_KEY w secrets/.env — realny Projectly niedostępny.")
    return client


def lista_projektow(client=None):
    client = client or _real_client()
    client._ensure_directory()
    return [(p.get("name"), p.get("status"), p.get("id")) for p in client._projects]


def zaloz_zadanie(tytul, opis, projekt, przypisz="bot", client=None, wykonaj=False):
    """Zwraca {'utworzone': bool, 'task_id': str|None, 'projekt_id': str|None, 'detal': str}.
    Bez wykonaj=True nic nie zapisuje — zwraca podgląd."""
    client = client or _real_client()
    projekt_id = client._project_id_by_name(projekt)
    if not projekt_id:
        dostepne = ", ".join(n for n, s, _ in lista_projektow(client) if s == "active")
        return {"utworzone": False, "task_id": None, "projekt_id": None,
                "detal": f"Nie znaleziono projektu '{projekt}'. Aktywne projekty: {dostepne}"}

    if not wykonaj:
        return {"utworzone": False, "task_id": None, "projekt_id": projekt_id,
                "detal": f"PODGLĄD (bez zapisu): '{tytul}' -> projekt '{projekt}', przypisane do '{przypisz}'."}

    task_id = client.create_task(title=tytul, description=opis, assigned_to=przypisz, project_id=projekt_id)
    return {"utworzone": bool(task_id), "task_id": task_id, "projekt_id": projekt_id,
            "detal": f"Utworzono zadanie {task_id} w projekcie '{projekt}'."}


def main():
    parser = argparse.ArgumentParser(description="Zakłada zadanie w realnym Projectly.")
    parser.add_argument("--tytul", help="Tytuł zadania")
    parser.add_argument("--opis", default="", help="Opis zadania (tu wklej adres źródła)")
    parser.add_argument("--projekt", default="Administracyjne", help="Nazwa projektu w Projectly")
    parser.add_argument("--przypisz", default="bot", help="Alias z projectly.yaml (bot = konto AI tej maszyny)")
    parser.add_argument("--lista-projektow", action="store_true", help="Wypisz projekty i zakończ")
    parser.add_argument("--yes", action="store_true", help="Faktycznie utwórz zadanie (bez tego: podgląd)")
    args = parser.parse_args()

    if args.lista_projektow:
        for nazwa, status, _ in lista_projektow():
            print(f"{status:10} {nazwa}")
        return 0

    if not args.tytul:
        parser.error("--tytul jest wymagany (albo użyj --lista-projektow)")

    wynik = zaloz_zadanie(args.tytul, args.opis, args.projekt, args.przypisz, wykonaj=args.yes)
    print(wynik["detal"])
    return 0 if (wynik["utworzone"] or not args.yes) else 1


if __name__ == "__main__":
    sys.exit(main())
