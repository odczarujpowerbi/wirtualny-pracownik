# Reguły projektu — Wirtualny pracownik AI

## Stack
- Język: Python 3.9+ (rdzeń), PowerShell 7 + Bash (bootstrap maszyn)
- Runner: pętla agenta (`app/runner_loop.py`), stan w SQLite (`app/state_store.py`)
- AI: Anthropic API (główna pętla), OpenRouter jako fallback, model wizyjny do walidacji zrzutów
- Kolejka zadań: Projectly (API + MCP) — jedyne źródło prawdy; dziś `MockProjectlyClient`
- Konfiguracja firmy: `app/config/*.yaml` (edytowalna bez zmiany kodu)
- Sekrety: `app/secrets/` (nigdy w repo), tworzone przez `bootstrap_init_secrets.py`
- Testy: uruchamialne lokalnie w trybie mock, bez kluczy API

## Tryb pracy
- Multi-agent TYLKO gdy zadania są niezależne.
- Czytanie/research → Haiku (explorer). Implementacja → Sonnet (implementer). Planowanie → Opus.
- Przy sekwencyjnych zależnościach lub edycji tych samych plików: jedna sesja.

## Zanim zaczniesz kodować
- Plan mode, zatwierdź plan, dopiero implementacja.
- Rozdziel własność plików między workerów. Nikt nie rusza cudzego zakresu.

## Zasady domenowe (z dokumentacji projektu)
- Hierarchia metod wykonania: API/MCP → CLI/skrypt → automatyzacja UI → computer use.
- Fail closed: przy niepewności zapisz stan i eskaluj, nie wykonuj działań nieodwracalnych.
- Klasyfikacja ryzyka: zielone (auto) / żółte (auto w granicach polityki, 3 walidatory) / czerwone (zawsze człowiek).
- Sekrety nigdy w repo/logach/screenshotach.
- Zmiany w kodzie/PBIP: branch + PR, nigdy bezpośrednio do main.
- **Pliki zapisywane w runtime (stan, flagi, raporty, cache) MUSZĄ trafiać do `app/runs/` albo `app/secrets/` (oba w .gitignore), NIGDY do ścieżki śledzonej przez git.** Inaczej `git pull` na maszynie konfliktuje z lokalną zmianą. Jeśli plik śledzony musi mieć wartości domyślne (np. harmonogram), trzymaj SZABLON w repo (`*.default.*`) i seeduj/domerguj lokalną kopię przy starcie (wzór: `schedule.default.yaml` → `schedule.yaml`). Naprawione tak: `schedule.yaml`, `role.json`, `STAN-SRODOWISKA.txt`.

## Bezpieczeństwo
- reviewer i explorer: tylko Read/Grep/Glob.
- Operacje na bazie tylko SELECT, chyba że jawnie zlecone inaczej.

## Dokumentacja
- Dokumentacja: docs/index.html — zestaw małych, samodzielnych stron (architektura, przepływ zadania, boty i persony, buyer persony, kontekst firmy, modele i koszty, bezpieczeństwo, panel operatora, skąd zadania, instalacja, mapa plików, stan i roadmapa). Jak dodać/zmienić stronę: docs/jak-edytowac.html. README.md w root = skrót o projekcie.
- Instalacja i konfiguracja maszyny: folder instalacja/ (Przygotuj-srodowisko.bat, Zaloguj.bat, postaw-od-zera.ps1)
- Stan kodu (co działa / czego brak): app/README.md
- **Mapa skryptów — który skrypt do czego, kiedy wywołać, "chcę zrobić X → wywołaj Y": app/MAPA-SKRYPTOW.md. Sprawdź TO PIERWSZE, zanim zaczniesz grepować repo w poszukiwaniu właściwego skryptu.**
- Stara dokumentacja (.md/PDF) usunięta z repo (jest w historii git). Nie odtwarzać bez potrzeby.

> Standardy kodu, git, testy i bezpieczeństwo załadowane globalnie z ~/.claude/rules/
