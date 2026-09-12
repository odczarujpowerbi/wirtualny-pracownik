"""
Folder zadania na SharePoint (lokalny mirror OneDrive, ONEDRIVE_TASKS_ROOT).

Jedno miejsce, w ktorym liczy sie sciezke folderu zadania. Wczesniej ta sama
logika stala w DWOCH plikach naraz (runner_loop._save_result_to_onedrive i
agentic_worker._onedrive_task_folder) — swiadomie zduplikowana, bo runner_loop
importuje agentic_worker, wiec import w druga strone byl cyklem. Osobny modul
usuwa cykl i duplikat.

Struktura (decyzja wlasciciela 12.09.2026):

    Zadania-Agenta/<Projekt>/<zadanie nadrzedne>/<zadanie>/

Zadanie bez rodzica dostaje folder wprost pod projektem. Wczesniej wszystko lezalo
plasko w korzeniu, a podzadania pisaly do folderu RODZICA — nie bylo widac, ktore
zadanie nalezy do ktorego projektu.

Stare foldery zostaja tam, gdzie sa (ponad sto zadan sprzed zmiany): zanim
zalozymy cokolwiek nowego, szukamy folderu po starym wzorcu w korzeniu i gdy
istnieje, uzywamy jego. Zadna sciezka nie jest przenoszona.

Fail-soft wszedzie: brak ONEDRIVE_TASKS_ROOT albo niezsynchronizowany OneDrive
-> None, czyli zadanie dziala dalej, tylko bez sladu na SharePoincie.
"""

import os
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

MAX_SLUG = 40
BEZ_PROJEKTU = "Bez projektu"
GRUPA_SUFFIX = "grupa"


def _slug(text, limit=MAX_SLUG):
    """Nazwa bezpieczna dla Windowsa i czytelna dla czlowieka."""
    tekst = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")
    tekst = re.sub(r"[^A-Za-z0-9]+", "-", tekst).strip("-").lower()
    return tekst[:limit] or "zadanie"


def root_path():
    """Korzen archiwum zadan albo None, gdy nie skonfigurowany/niezsynchronizowany."""
    root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    if not root:
        return None
    root_path_ = Path(root)
    # Rodzic musi istniec — inaczej zalozylibysmy sierocy folder poza biblioteka.
    if not root_path_.parent.exists():
        return None
    return root_path_


def _stary_folder(root, task_id):
    """Folder sprzed zmiany struktury (plasko w korzeniu) albo None."""
    if not root.exists() or not task_id:
        return None
    istniejace = sorted(root.glob(f"{task_id}_*"))
    return istniejace[0] if istniejace else None


def _folder_projektu(root, task, client):
    """Podfolder projektu. Nieznany projekt -> wspolny folder zapasowy, nie blad."""
    nazwa = None
    project_id = (task or {}).get("project_id")
    if client is not None and project_id:
        try:
            nazwa = client.project_name(project_id)
        except Exception:  # noqa: BLE001 — nazwa projektu to wygoda, nie warunek zapisu
            nazwa = None
    return root / (_slug(nazwa, limit=60) if nazwa else BEZ_PROJEKTU)


def _folder_rodzica(folder_projektu, parent_id):
    """Folder zadania nadrzednego. Gdy rodzic nie ma jeszcze swojego folderu
    (podzadanie przetworzone przed rodzicem), zakladamy go po samym id — nazwa
    doklei sie, gdy rodzic bedzie przetwarzany."""
    if not parent_id:
        return None
    if folder_projektu.exists():
        istniejace = sorted(folder_projektu.glob(f"{parent_id}_*"))
        if istniejace:
            return istniejace[0]
    return folder_projektu / f"{parent_id}_{GRUPA_SUFFIX}"


def sciezka(task, client=None, root=None):
    """Sciezka folderu TEGO zadania albo None. Nie tworzy katalogu."""
    korzen = Path(root) if root else root_path()
    if korzen is None:
        return None

    task = task or {}
    task_id = task.get("task_id") or "zadanie"
    parent_id = task.get("parent_task_id")

    # Stare zadania: folder w korzeniu wygrywa, zeby wynik trafil tam, gdzie
    # poprzednie pliki tego samego zadania (albo jego rodzica, jak dotad).
    stary = _stary_folder(korzen, task_id) or _stary_folder(korzen, parent_id)
    if stary:
        return stary

    folder_projektu = _folder_projektu(korzen, task, client)
    rodzic = _folder_rodzica(folder_projektu, parent_id)
    baza = rodzic if rodzic is not None else folder_projektu
    data = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return baza / f"{task_id}_{data}_{_slug(task.get('title'))}"


def utworz(task, client=None, root=None):
    """Sciezka folderu zadania, utworzona na dysku. None, gdy nie ma gdzie pisac."""
    folder = sciezka(task, client=client, root=root)
    if folder is None:
        return None
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[task_folder] Nie moge utworzyc folderu zadania ({exc}) — pomijam zapis na SharePoint.")
        return None
    return folder
