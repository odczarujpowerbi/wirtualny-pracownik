"""
Kopiowanie wiedzy o projekcie z Projectly do repozytorium projektu.

Zasada jest jedna i nie ma od niej wyjatku: JEDEN KIERUNEK. Projectly nadpisuje
pliki w repozytorium, nigdy odwrotnie. Dzieki temu czlowiek ma jedno miejsce,
w ktorym pisze o projekcie (dokumentacja projektu w Projectly), a agent ma to
samo w repozytorium, obok kodu, i przezywa to zerwanie piaskownicy po zadaniu.

Tresc kopiujemy BEZ przerabiania (decyzja wlasciciela 12.09.2026): strona
dokumentacji schodzi jako plik .md, zalacznik jako oryginalny plik.

    <repo>/baza-wiedzy-projectly/
        _INDEKS.md            <- co i kiedy skopiowano
        wymagania-projektu.md
        zalaczniki/brief.pdf

Fail-soft w calosci: blad Projectly albo blad zapisu konczy sie zwroceniem
informacji, co sie udalo, a nie wyjatkiem. Brak wiedzy w projekcie to nie blad,
tylko pusty wynik.
"""

import base64
from datetime import datetime, timezone
from pathlib import Path

FOLDER_WIEDZY = "baza-wiedzy-projectly"
FOLDER_ZALACZNIKOW = "zalaczniki"
PLIK_INDEKSU = "_INDEKS.md"


def _bezpieczna_nazwa(nazwa, domyslna):
    """Sama nazwa pliku, bez sciezki: zalacznik z Projectly nie moze wskazac
    katalogu poza folderem wiedzy (fail-closed wobec nazw typu ../../secrets)."""
    czysta = Path(str(nazwa or "")).name.strip()
    return czysta or domyslna


def _zapisz_strony(client, project_id, folder, wynik):
    """Strony dokumentacji jako pliki .md. Zwraca liste nazw plikow."""
    try:
        dokumentacja = client.documentation(project_id)
    except Exception as exc:  # noqa: BLE001 — brak wiedzy nie moze zablokowac zadania
        wynik["bledy"].append(f"nie udało się pobrać dokumentacji: {exc}")
        return []

    strony = (dokumentacja or {}).get("pages") or []
    zapisane = []
    for strona in strony:
        page_id = strona.get("id")
        if not page_id:
            continue
        try:
            plik = client.doc_file(project_id, page_id)
        except Exception as exc:  # noqa: BLE001
            wynik["bledy"].append(f"strona {strona.get('title') or page_id}: {exc}")
            continue
        if not isinstance(plik, dict) or plik.get("error"):
            wynik["bledy"].append(f"strona {strona.get('title') or page_id}: "
                                  f"{(plik or {}).get('error', 'brak treści')}")
            continue
        nazwa = _bezpieczna_nazwa(plik.get("fileName"), f"{page_id}.md")
        (folder / nazwa).write_text(plik.get("content") or "", encoding="utf-8")
        zapisane.append(nazwa)
    return zapisane


def _zapisz_zalaczniki(client, dokumentacja, folder, wynik):
    """Zalaczniki stron jako oryginalne pliki. Zwraca liste nazw plikow."""
    strony = (dokumentacja or {}).get("pages") or []
    zapisane = []
    for strona in strony:
        for zalacznik in strona.get("attachments") or []:
            att_id = zalacznik.get("id")
            if not att_id:
                continue
            try:
                dane = client.doc_attachment(att_id)
            except Exception as exc:  # noqa: BLE001
                wynik["bledy"].append(f"załącznik {zalacznik.get('name') or att_id}: {exc}")
                continue
            if not isinstance(dane, dict) or dane.get("error") or not dane.get("dataBase64"):
                wynik["bledy"].append(f"załącznik {zalacznik.get('name') or att_id}: brak zawartości")
                continue
            nazwa = _bezpieczna_nazwa(dane.get("name"), att_id)
            try:
                (folder / nazwa).write_bytes(base64.b64decode(dane["dataBase64"]))
            except (ValueError, OSError) as exc:
                wynik["bledy"].append(f"załącznik {nazwa}: {exc}")
                continue
            zapisane.append(nazwa)
    return zapisane


def _indeks(project_id, strony, zalaczniki):
    teraz = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    linie = [
        "# Wiedza o projekcie z Projectly",
        "",
        f"Skopiowane automatycznie {teraz} z projektu `{project_id}`.",
        "Ten folder jest **nadpisywany** przy każdym zadaniu. Nie edytuj go tutaj,",
        "zmiany wprowadzaj w dokumentacji projektu w Projectly.",
        "",
        "## Strony dokumentacji",
    ]
    linie += [f"- {n}" for n in strony] or ["- (brak)"]
    linie += ["", "## Załączniki"]
    linie += [f"- {FOLDER_ZALACZNIKOW}/{n}" for n in zalaczniki] or ["- (brak)"]
    return "\n".join(linie) + "\n"


def synchronizuj(client, project_id, repo_path):
    """Kopiuje wiedzę projektu do repozytorium. Nigdy nie rzuca.

    Zwraca {"ok", "strony", "zalaczniki", "folder", "bledy"}."""
    wynik = {"ok": False, "strony": [], "zalaczniki": [], "folder": None, "bledy": []}
    if client is None or not project_id or not repo_path:
        wynik["bledy"].append("brak klienta, projektu albo repozytorium")
        return wynik

    folder = Path(repo_path) / FOLDER_WIEDZY
    folder_zalacznikow = folder / FOLDER_ZALACZNIKOW
    try:
        folder_zalacznikow.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        wynik["bledy"].append(f"nie udało się utworzyć folderu wiedzy: {exc}")
        return wynik

    wynik["folder"] = str(folder)
    wynik["strony"] = _zapisz_strony(client, project_id, folder, wynik)

    try:
        dokumentacja = client.documentation(project_id)
    except Exception as exc:  # noqa: BLE001
        dokumentacja = None
        wynik["bledy"].append(f"nie udało się pobrać listy załączników: {exc}")
    wynik["zalaczniki"] = _zapisz_zalaczniki(client, dokumentacja, folder_zalacznikow, wynik)

    try:
        (folder / PLIK_INDEKSU).write_text(_indeks(project_id, wynik["strony"], wynik["zalaczniki"]),
                                           encoding="utf-8")
    except OSError as exc:
        wynik["bledy"].append(f"nie udało się zapisać indeksu: {exc}")

    wynik["ok"] = bool(wynik["strony"] or wynik["zalaczniki"])
    return wynik
