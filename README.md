# Wirtualny Pracownik AI

Wirtualny pracownik działający niezależnie od laptopów zespołu: cyklicznie pobiera zadania, uruchamia skrypty i narzędzia, obsługuje aplikacje (Power BI, Office, przeglądarka), **waliduje wyniki** i zostawia **pełny ślad audytowy** każdej decyzji. Chodzi 24/7 na dedykowanej maszynie i jest sterowalny oraz podglądalny z lokalnego dashboardu.

## Od czego zacząć

Pełna dokumentacja: **[`docs/index.html`](./docs/index.html)**. Otwórz dwuklikiem, bez serwera.
Lewy pasek prowadzi przez wszystkie sekcje, każda jest osobnym plikiem w `docs/sekcje/`.

| Chcę... | Otwórz sekcję |
|---|---|
| **Zrozumieć, czym to jest** (język biznesowy, bez kodu) | `01-co-to-jest` |
| **Zobaczyć, jak płynie praca** (diagram drogi zadania) | `02-droga-zadania` |
| **Wiedzieć, skąd pewność jakości wyniku** | `04-kontrola-jakosci` |
| **Zainstalować i uruchomić** (krok po kroku) | `11-instalacja` |
| **Włączyć, wyłączyć albo podejrzeć bota** | `08-sterowanie` |
| **Sprawdzić, co działa, a co jest planem** | `13-co-dziala`, `14-co-dalej` |

## Szybki start (skrót instrukcji)

1. **Pusta maszyna** (Windows Server 2022 / Windows 11), PowerShell jako administrator — jedna linia pobiera git, klonuje repo i uruchamia instalator:
   ```powershell
   $s="$env:TEMP\postaw.ps1"; irm https://raw.githubusercontent.com/odczarujpowerbi/wirtualny-pracownik/main/instalacja/skrypty/postaw-od-zera.ps1 -OutFile $s; powershell -ExecutionPolicy Bypass -File $s
   ```
   Repo już jest? Kliknij `instalacja\Przygotuj-srodowisko.bat` (jako administrator). Instalacja jest **bezobsługowa**.
2. Uzupełnij dostępy w `app\secrets\.env` (i `app\secrets\mcp\*.json`). Szczegóły w instrukcji.
3. Zaloguj się na konta: `instalacja\Zaloguj.bat` (osobny, szybki krok po instalacji).
4. Przy zalogowaniu startuje **tylko nadzorca** (`start-nadzorca.bat`). To on odpala boty, i wyłącznie te włączone zadaniem sterującym w Projectly. Ręczny start jednego bota (diagnostyka): `start-agent-dev.bat`. Podgląd: `start-dashboard.bat` (albo `python app\dashboard.py`) → http://127.0.0.1:8787/

## Główny folder — co jest czym

- **`instalacja/`** — instalator (`Przygotuj-srodowisko.bat`, `Zaloguj.bat`, `postaw-od-zera.ps1`).
- **`docs/`** — dokumentacja projektu: powłoka `index.html` z lewym paskiem nawigacji, sekcje w `docs/sekcje/`, wspólny wygląd w `docs/assets/`.
- **`app/`** — kod (rdzeń agenta, boty, dashboard, skrypty instalacyjne). Stan i sekrety w `app/runs/` i `app/secrets/` (poza repo).
- **`aktualizuj-repo.bat`** — pobranie nowego kodu z GitHub (dwuklik).
- **`start-agent-dev.bat`** / **`start-agent-checker.bat`** / **`start-agent-marketing.bat`** / **`start-agent-zarzad.bat`** — ręczny start pętli jednego z czterech botów (każdy osobny proces/okno). **`start-agent-all.bat`** — odpala wszystkie cztery naraz, w osobnych oknach.
- **`start-dashboard.bat`** — ręczny start panelu operatora (`python app\dashboard.py` → http://127.0.0.1:8787/).

## Stack

- **System:** Windows Server 2022 (docelowo) albo Windows 11. Dedykowana maszyna 24/7.
- **Rdzeń:** Python + Harmonogram zadań Windows. Model główny: Claude (subskrypcja przez `claude` albo API). Modele lokalne: Ollama (druga opinia / wizja ekranu).
- **Kolejka zadań:** Projectly (API + MCP); tryb mock lokalnie bez kluczy. Dodatkowe źródła: notatnik i formularz w dashboardzie.
- **Repozytoria:** kod i PBIP na GitHub; agent pracuje na branchach + PR, nie zapisuje bezpośrednio do `main`.

## Zasady

- Hierarchia metod wykonania: **API/MCP → pliki/CLI/skrypt → automatyzacja UI → computer use**.
- **Fail closed:** przy niepewności agent nie robi rzeczy nieodwracalnej — zapisuje stan i eskaluje.
- Klasy działań: **zielone** (auto) / **żółte** (auto w granicach polityki, walidatory) / **czerwone** (zawsze człowiek).
- Model uruchamia **tylko zarejestrowane narzędzia** (kontrakt uprawnień), nigdy dowolny shell.
- Sekrety nigdy w repo/logach/zrzutach.
