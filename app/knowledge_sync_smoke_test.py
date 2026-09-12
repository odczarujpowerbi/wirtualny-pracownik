"""
Test dymny knowledge_sync.py. Zero sieci: klient Projectly to atrapa, repozytorium
to katalog tymczasowy.

Uzycie:
    python knowledge_sync_smoke_test.py
"""

import base64
import sys
import tempfile
from pathlib import Path

import knowledge_sync

TRESC_PDF = b"%PDF-1.4 udawany plik"


class _Klient:
    """Projekt z dwiema stronami dokumentacji i jednym zalacznikiem."""

    def documentation(self, project_id):
        return {"count": 2, "pages": [
            {"id": "S-1", "title": "Wymagania projektu", "attachments": [
                {"id": "A-1", "name": "brief.pdf", "mimeType": "application/pdf"},
            ]},
            {"id": "S-2", "title": "Zakres wdrożenia", "attachments": []},
        ]}

    def doc_file(self, project_id, page_id):
        tresc = {"S-1": "# Wymagania projektu\n\nTreść wymagań.\n",
                 "S-2": "# Zakres wdrożenia\n\nCo robimy.\n"}[page_id]
        nazwa = {"S-1": "wymagania-projektu.md", "S-2": "zakres-wdrozenia.md"}[page_id]
        return {"fileName": nazwa, "title": page_id, "format": "md", "content": tresc}

    def doc_attachment(self, attachment_id):
        return {"id": attachment_id, "name": "brief.pdf", "mimeType": "application/pdf",
                "dataBase64": base64.b64encode(TRESC_PDF).decode("ascii")}


class _KlientZlosliwy(_Klient):
    """Zalacznik probuje wyjsc poza folder wiedzy nazwa pliku."""

    def doc_attachment(self, attachment_id):
        return {"id": attachment_id, "name": "../../../secrets/.env", "mimeType": "text/plain",
                "dataBase64": base64.b64encode(b"SEKRET").decode("ascii")}


class _KlientPadajacy:
    def documentation(self, project_id):
        raise RuntimeError("Projectly nieosiagalne")

    def doc_file(self, project_id, page_id):
        raise RuntimeError("Projectly nieosiagalne")

    def doc_attachment(self, attachment_id):
        raise RuntimeError("Projectly nieosiagalne")


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # 1. Happy path: strony jako pliki .md, zalacznik jako oryginalny plik, indeks.
    repo = Path(tempfile.mkdtemp())
    wynik = knowledge_sync.synchronizuj(_Klient(), "P-1", repo)
    folder = repo / knowledge_sync.FOLDER_WIEDZY

    checks.append(("Synchronizacja konczy sie sukcesem", wynik["ok"] is True))
    checks.append(("Obie strony zapisane jako pliki .md",
                   (folder / "wymagania-projektu.md").is_file()
                   and (folder / "zakres-wdrozenia.md").is_file()))
    checks.append(("Tresc strony skopiowana BEZ przerabiania",
                   (folder / "wymagania-projektu.md").read_text(encoding="utf-8")
                   == "# Wymagania projektu\n\nTreść wymagań.\n"))
    checks.append(("Zalacznik zapisany jako oryginalny plik binarny",
                   (folder / knowledge_sync.FOLDER_ZALACZNIKOW / "brief.pdf").read_bytes() == TRESC_PDF))
    checks.append(("Indeks wymienia strony i zalaczniki",
                   "wymagania-projektu.md" in (folder / knowledge_sync.PLIK_INDEKSU).read_text(encoding="utf-8")
                   and "brief.pdf" in (folder / knowledge_sync.PLIK_INDEKSU).read_text(encoding="utf-8")))
    checks.append(("Indeks mowi, ze folder jest nadpisywany",
                   "nadpisywany" in (folder / knowledge_sync.PLIK_INDEKSU).read_text(encoding="utf-8")))

    # 2. Powtorzona synchronizacja nadpisuje, nie dubluje plikow.
    knowledge_sync.synchronizuj(_Klient(), "P-1", repo)
    checks.append(("Powtorzenie nie dubluje plikow", len(list(folder.glob("*.md"))) == 3))

    # 3. Bezpieczenstwo: nazwa zalacznika nie moze wyprowadzic zapisu poza folder.
    repo2 = Path(tempfile.mkdtemp())
    knowledge_sync.synchronizuj(_KlientZlosliwy(), "P-1", repo2)
    zalaczniki = repo2 / knowledge_sync.FOLDER_WIEDZY / knowledge_sync.FOLDER_ZALACZNIKOW
    checks.append(("Zalacznik z ../ laduje w folderze zalacznikow, nie wyzej",
                   (zalaczniki / ".env").is_file() and not (repo2 / "secrets").exists()))

    # 4. Error case: Projectly nieosiagalne -> ok=False, blad opisany, bez wyjatku.
    repo3 = Path(tempfile.mkdtemp())
    wynik_blad = knowledge_sync.synchronizuj(_KlientPadajacy(), "P-1", repo3)
    checks.append(("Blad Projectly: ok=False i opis bledu, bez wyjatku",
                   wynik_blad["ok"] is False and len(wynik_blad["bledy"]) > 0))

    # 5. Error case: brak klienta albo projektu.
    checks.append(("Brak klienta -> ok=False",
                   knowledge_sync.synchronizuj(None, "P-1", repo3)["ok"] is False))
    checks.append(("Brak projektu -> ok=False",
                   knowledge_sync.synchronizuj(_Klient(), None, repo3)["ok"] is False))

    print("\n--- Wynik testu dymnego knowledge_sync ---")
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
