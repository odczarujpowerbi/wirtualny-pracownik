"""
Test dymny sharepoint_link.py — budowa linku do folderu SharePoint z lokalnej
ścieżki OneDrive. Zero sieci, zero prawdziwego configu (własny słownik
podstawiany zamiast config/sharepoint.yaml).

Użycie:
    python sharepoint_link_smoke_test.py
"""

import sys

import sharepoint_link

CONFIG = {
    "site_host": "example.sharepoint.com",
    "site_path": "/sites/Test",
    "library": "Dokumenty",
    "root_folder": "Zadania-Agenta",
}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    checks.append(("library_url: sklejony adres z config", sharepoint_link.library_url(CONFIG)
                   == "https://example.sharepoint.com/sites/Test/Dokumenty"))

    url = sharepoint_link.folder_url(r"C:\Users\ktos\OneDrive\Zadania-Agenta\T-1_2026-08-29_test", config=CONFIG)
    checks.append(("folder_url: bierze TYLKO ostatni segment ścieżki lokalnej",
                   url == "https://example.sharepoint.com/sites/Test/Dokumenty/Zadania-Agenta/T-1_2026-08-29_test"))

    url_spacje = sharepoint_link.folder_url("T-2_2026-08-29_zadanie z polskimi znakami ąę", config=CONFIG)
    checks.append(("folder_url: spacje i polskie znaki URL-encodowane (klikalny link)",
                   "%20" in url_spacje and " " not in url_spacje))

    checks.append(("folder_url: pusty folder_path -> None, bez wyjątku",
                   sharepoint_link.folder_url("", config=CONFIG) is None
                   and sharepoint_link.folder_url(None, config=CONFIG) is None))

    checks.append(("folder_url: błędny/niekompletny config -> None, fail-soft",
                   sharepoint_link.folder_url("T-3", config={"site_host": "x"}) is None))

    checks.append(("Prawdziwy config/sharepoint.yaml faktycznie się wczytuje",
                   sharepoint_link.folder_url("T-4_test") is not None
                   and sharepoint_link.folder_url("T-4_test").startswith("https://")))

    print("\n--- Wynik testu dymnego sharepoint_link ---")
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
