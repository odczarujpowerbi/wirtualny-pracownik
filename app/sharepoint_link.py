"""
Buduje klikalny link do folderu SharePoint z lokalnej ścieżki OneDrive
(ONEDRIVE_TASKS_ROOT, patrz runner_loop._save_result_to_onedrive) — jedno
miejsce czytające config/sharepoint.yaml, żeby adres biblioteki nie był
zaszyty osobno w każdym miejscu, które go potrzebuje (runner_loop.py przy
komentarzu na zakończonym zadaniu, docelowo też digest_generator.py).

UCZCIWA GRANICA: zweryfikowana jest tylko część adresu do biblioteki włącznie
(site_host/site_path/library) oraz root_folder ("Zadania-Agenta") — patrz
digest_generator.py, gdzie ten sam wzorzec linku jest już używany na
produkcji. Doklejenie nazwy KONKRETNEGO folderu zadania jest nowe (29.08.2026),
nie potwierdzone osobno — jeśli link nie otworzy się poprawnie, sprawdź czy
nazwa folderu w SharePoint dokładnie odpowiada nazwie folderu lokalnego
(OneDrive powinien je synchronizować 1:1).

Użycie:
    python sharepoint_link.py <lokalna_sciezka_folderu>
"""

import sys
from pathlib import Path
from urllib.parse import quote

import yaml

CONFIG_PATH = Path(__file__).parent / "config" / "sharepoint.yaml"


def _load_config(path=CONFIG_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def library_url(config=None):
    cfg = config or _load_config()
    return f"https://{cfg['site_host']}{cfg['site_path']}/{cfg['library']}"


def folder_url(folder_path, config=None):
    """folder_path: ścieżka LOKALNA (albo sama nazwa) do folderu zadania pod
    ONEDRIVE_TASKS_ROOT — używamy TYLKO ostatniego segmentu (nazwa folderu),
    resztę adresu (biblioteka + root_folder) bierzemy z configu. Zwraca None
    dla pustego folder_path albo błędu configu (fail-soft — brak linku nie
    może zablokować zapisu/publikacji komentarza)."""
    if not folder_path:
        return None
    try:
        cfg = config or _load_config()
        nazwa = Path(folder_path).name
        return f"{library_url(cfg)}/{quote(cfg['root_folder'])}/{quote(nazwa)}"
    except (OSError, KeyError, TypeError):
        return None


def main():
    if len(sys.argv) < 2:
        print("Użycie: python sharepoint_link.py <lokalna_sciezka_folderu>")
        return 1
    print(folder_url(sys.argv[1]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
