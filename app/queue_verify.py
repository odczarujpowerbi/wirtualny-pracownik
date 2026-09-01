"""
Diagnoza "dodałem zadanie, a bot go nie widzi" — dla KAŻDEJ roli naraz, bez
zgadywania (pytanie właściciela 01.09.2026 o kolejkę marketingu).

Odpowiada na trzy pytania:
  1. Jakie zadania ma w kolejce każda rola (dokładnie to, co zobaczy runner_loop:
     get_new_tasks, czyli status todo + przypisane do konta AI TEJ roli).
  2. Po jakich projektach ta rola w ogóle szuka. Konta AI mają w Projectly RÓŻNE
     uprawnienia — zadanie w projekcie, którego dane konto nie widzi, nie
     istnieje dla tego bota, choć w interfejsie wygląda normalnie. To była realna
     przyczyna: "AI - Marketing" nie widzi projektu LDIT, "AI-Checker" widzi
     tylko dwa projekty z siedmiu.
  3. Które projekty są niewidoczne dla których rol (luki uprawnień) — czyli
     lista rzeczy do klikniecia w Projectly, nie w kodzie.

Zasada, ktora ten skrypt weryfikuje (decyzja wlasciciela): kazdy agent patrzy na
WSZYSTKIE projekty, ale WYLACZNIE na swoje zadania. Filtr po koncie robi serwer
(assigneeId), a po projektach iteruje klient - wiec kod tego nie ogranicza.
Ogranicza to tylko dostep konta AI do projektu.

Zadania STERUJACE botem ("Kontrola bota: <rola>") sie tu nie licza - sa odsiane
z kolejki pracy w projectly_client.is_control_task.

Użycie:
    python queue_verify.py
"""

import agent_launcher
import env_bootstrap  # noqa: F401  # wczytuje secrets/.env (tokeny per rola) + UTF-8 na stdout
import projectly_client


def zbadaj_role(role, client=None):
    """Kolejka i zasięg JEDNEJ roli. Zwraca słownik, nigdy nie rzuca — jedna
    rola bez tokenu/z błędem sieci nie może przerwać diagnozy pozostałych."""
    try:
        client = client or projectly_client.client_for_role(role)
        projekty = client.polled_project_names()
        zadania = client.get_new_tasks()
    except Exception as exc:  # noqa: BLE001 — diagnostyka ma pokazać błąd, nie wywalić się
        return {"role": role, "blad": str(exc), "projekty": [], "kolejka": []}
    return {
        "role": role,
        "konto": projectly_client.own_account_name(role),
        "projekty": projekty,
        "kolejka": [{"title": t.get("title"), "status": t.get("status"),
                     "projekt": _nazwa_projektu(client, t.get("project_id"))}
                    for t in zadania],
        "blad": None,
    }


def _nazwa_projektu(client, project_id):
    if not project_id:
        return "?"
    try:
        return client.project_name(project_id) or project_id
    except Exception:  # noqa: BLE001 — nazwa projektu to ozdoba raportu, nie jego treść
        return project_id


def luki_widocznosci(raporty):
    """Projekt -> które role go widzą, a które nie. Tylko projekty, których NIE
    widzi co najmniej jedna rola — bo to jest lista do naprawy w Projectly."""
    widok = {r["role"]: set(r["projekty"]) for r in raporty}
    wszystkie = sorted(set().union(*widok.values())) if widok else []
    luki = []
    for nazwa in wszystkie:
        brak = sorted(rola for rola, projekty in widok.items() if nazwa not in projekty)
        if brak:
            luki.append({"projekt": nazwa,
                         "widza": sorted(rola for rola in widok if nazwa in widok[rola]),
                         "nie_widza": brak})
    return luki


def zbadaj(roles=None, client_factory=None):
    roles = roles if roles is not None else list(agent_launcher.AGENT_BAT_FILES)
    raporty = [zbadaj_role(rola, client=client_factory(rola) if client_factory else None)
               for rola in roles]
    return {"role": raporty, "luki": luki_widocznosci(raporty)}


def wypisz(wynik):
    print(f"{'Rola':<12}{'Konto AI':<18}{'Projektów':>10}{'W kolejce':>11}  Uwagi")
    for r in wynik["role"]:
        uwaga = f"BŁĄD: {r['blad']}" if r["blad"] else ("kolejka pusta" if not r["kolejka"] else "")
        print(f"{r['role']:<12}{str(r.get('konto') or '?'):<18}"
              f"{len(r['projekty']):>10}{len(r['kolejka']):>11}  {uwaga}")

    for r in wynik["role"]:
        if r["kolejka"]:
            print(f"\nKolejka '{r['role']}' (to, co zobaczy runner_loop):")
            for z in r["kolejka"]:
                print(f"    [{z['projekt']}] {z['status']} — {z['title']}")

    if not wynik["luki"]:
        print("\nKażda rola widzi każdy projekt — brak luk w uprawnieniach.")
        return
    print("\nLUKI UPRAWNIEŃ (do naprawy w Projectly, nie w kodzie) — zadanie w projekcie,")
    print("którego konto AI nie widzi, dla tego bota NIE ISTNIEJE:")
    for luka in wynik["luki"]:
        print(f"    {luka['projekt']:<45} widzą: {','.join(luka['widza']) or '-'}"
              f"   NIE WIDZĄ: {','.join(luka['nie_widza'])}")


def main():
    wypisz(zbadaj())


if __name__ == "__main__":
    main()
