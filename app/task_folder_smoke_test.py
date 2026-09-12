"""
Test dymny task_folder.py. Zero sieci i zero dotykania prawdziwego OneDrive:
korzen archiwum podawany jawnie (parametr root), klient Projectly to atrapa.

Uzycie:
    python task_folder_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import task_folder

ZADANIE = {"task_id": "T-100", "title": "Raport tygodniowy", "project_id": "P-1"}
PODZADANIE = {"task_id": "T-101", "title": "Zbierz dane", "project_id": "P-1", "parent_task_id": "T-100"}


class _Klient:
    def __init__(self, nazwa="Administracyjne"):
        self._nazwa = nazwa

    def project_name(self, project_id):
        return self._nazwa


class _KlientPadajacy:
    def project_name(self, project_id):
        raise RuntimeError("Projectly nieosiagalne")


def _korzen():
    korzen = Path(tempfile.mkdtemp()) / "Zadania-Agenta"
    korzen.mkdir(parents=True, exist_ok=True)
    return korzen


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. Zadanie glowne: <korzen>/<Projekt>/<id>_<data>_<tytul>
    korzen = _korzen()
    folder = task_folder.sciezka(ZADANIE, client=_Klient(), root=korzen)
    checks.append(("Zadanie glowne laduje w folderze projektu",
                   folder.parent.name == "administracyjne" and folder.parent.parent == korzen))
    checks.append(("Nazwa folderu zaczyna sie od id zadania", folder.name.startswith("T-100_")))
    checks.append(("Nazwa folderu niesie tytul", folder.name.endswith("raport-tygodniowy")))

    # 2. Podzadanie: wlasny folder POD folderem rodzica (nie wspolny z rodzicem).
    folder_rodzica = task_folder.utworz(ZADANIE, client=_Klient(), root=korzen)
    folder_dziecka = task_folder.sciezka(PODZADANIE, client=_Klient(), root=korzen)
    checks.append(("Podzadanie ma WLASNY folder, nie pisze do folderu rodzica",
                   folder_dziecka != folder_rodzica))
    checks.append(("Folder podzadania lezy POD folderem rodzica",
                   folder_dziecka.parent == folder_rodzica))

    # 3. Podzadanie przetworzone PRZED rodzicem: folder rodzica powstaje po samym id.
    korzen2 = _korzen()
    sierota = task_folder.sciezka(PODZADANIE, client=_Klient(), root=korzen2)
    checks.append(("Podzadanie bez folderu rodzica: grupa zakladana po id rodzica",
                   sierota.parent.name == "T-100_grupa"))

    # 4. Stare, plaskie foldery zostaja nietkniete i nadal sa uzywane.
    korzen3 = _korzen()
    stary = korzen3 / "T-100_2026-08-22_raport-tygodniowy"
    stary.mkdir(parents=True, exist_ok=True)
    checks.append(("Stary plaski folder zadania wygrywa nad nowa struktura",
                   task_folder.sciezka(ZADANIE, client=_Klient(), root=korzen3) == stary))
    checks.append(("Podzadanie starego zadania nadal pisze do folderu rodzica",
                   task_folder.sciezka(PODZADANIE, client=_Klient(), root=korzen3) == stary))

    # 5. Fail-soft: brak nazwy projektu i blad klienta nie moga wywrocic zapisu.
    korzen4 = _korzen()
    checks.append(("Blad Projectly -> folder zapasowy, bez wyjatku",
                   task_folder.sciezka(ZADANIE, client=_KlientPadajacy(), root=korzen4).parent.name
                   == task_folder.BEZ_PROJEKTU))
    checks.append(("Brak klienta -> folder zapasowy",
                   task_folder.sciezka(ZADANIE, client=None, root=korzen4).parent.name
                   == task_folder.BEZ_PROJEKTU))

    # 6. Brak skonfigurowanego korzenia -> None (zadanie dziala dalej, bez sladu).
    checks.append(("Brak korzenia archiwum -> None",
                   task_folder.sciezka(ZADANIE, client=_Klient(), root=None) is None
                   or task_folder.root_path() is not None))

    # 7. utworz() realnie zaklada katalog.
    utworzony = task_folder.utworz(PODZADANIE, client=_Klient(), root=_korzen())
    checks.append(("utworz() zaklada katalog na dysku", utworzony is not None and utworzony.is_dir()))

    print("\n--- Wynik testu dymnego task_folder ---")
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
