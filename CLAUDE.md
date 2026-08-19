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

## Bezpieczeństwo
- reviewer i explorer: tylko Read/Grep/Glob.
- Operacje na bazie tylko SELECT, chyba że jawnie zlecone inaczej.

## Dokumentacja
- Koncepcja i architektura: README.md (root) + folder docs/ (PLAN-WDROZENIA.md, ZESPOL-BOTOW.md, SKRYPTY.md, SKALOWANIE.md, przeplyw.html, INSTRUKCJA-WDROZENIA.md, ...)
- Instalacja i konfiguracja maszyny: folder instalacja/ (Przygotuj-srodowisko.bat, Zaloguj.bat)
- Stan kodu (co działa / czego brak): app/README.md

> Standardy kodu, git, testy i bezpieczeństwo załadowane globalnie z ~/.claude/rules/
