# Przygotowanie środowiska na nowej maszynie

## Zupełnie pusta maszyna (nic nie ma: ani repo, ani git)

Otwórz **PowerShell jako administrator** i wklej jedną linię — pobierze gita, sklonuje repo i uruchomi cały instalator:

```powershell
$s="$env:TEMP\postaw.ps1"; irm https://raw.githubusercontent.com/odczarujpowerbi/wirtualny-pracownik/main/instalacja/postaw-od-zera.ps1 -OutFile $s; powershell -ExecutionPolicy Bypass -File $s
```

Domyślnie klonuje do `%USERPROFILE%\wirtualny-pracownik`. Opcje: `-InstallPath`, `-RepoUrl`, `-Branch`, `-SkipOffice`, `-SkipLocalModel`, `-SkipLogins` (dopisz na końcu polecenia `-File $s`).

## Repo już jest na maszynie

Jeden klik: **`Przygotuj-srodowisko.bat`** (dwuklik). Na świeżej maszynie kliknij prawym → *Uruchom jako administrator* (część instalatorów tego wymaga; inaczej działa per-user).

## Co robi (kolejno)

1. **Git** — wymagane.
2. **Python 3.11+** — wymagane.
3. **Claude Code (CLI)** — naped głównego modelu agenta.
4. **VS Code + rozszerzenie Claude Code** — kodowanie z agentem w edytorze (poprawki na stronie w repo).
5. **Microsoft Office / 365 Apps** — Excel, Word, Outlook (klasyczny), PowerPoint (kilka GB; pomiń: `-SkipOffice`). Używa **dołączonego instalatora** `instalacja/office/OfficeSetup.exe` (fallback: winget). Uruchamiany **w tle** — usługa Click-to-Run dociąga pakiet sama, a instalator **nie czeka** i leci z kolejnymi krokami. Instaluje się **bez logowania**; aktywacja później kontem Business Standard (docelowo może ją przejąć agent computer-use). Boty pracują na Office przez MCP do Excela oraz przez boty czytające ekran. *Uwaga: raport stanu (krok 15) może pokazać Office jako BRAK, jeśli pobieranie w tle jeszcze trwa — to normalne.*
6. **Aplikacje** — Power BI Desktop, Obsidian, Teams, Outlook (nowy), Google Chrome (pomiń: `-SkipApps`).
   - **6b. Terminal Windows + konfiguracja pod Claude** (pomiń: `-SkipTerminal`) — instaluje Terminal i dodaje dwa profile (fragment WT, niedestrukcyjnie): **„Wirtualny Pracownik"** (PowerShell w katalogu projektu) i **„Claude — Wirtualny Pracownik"** (od razu odpala `claude` w projekcie). Widoczne w rozwijanym menu Terminala.
   - **6c. Statuslinia Claude** — pasek na dole terminala z limitami (blok 5h / tydzień / dziś) przez claude-powerline; `statusLine` dopisywany do `~/.claude/settings.json` (merge). Ten sam pasek widzi też agent — patrz `usage_monitor.py` (dashboard: „Claude 5h" + „szac. zadań").
7. **Modele lokalne (Ollama)** — tania druga opinia / computer use (kilka GB; pomiń: `-SkipLocalModel`).
8. **OneDrive** — lokalny sync projektów stron i biblioteki skilli.
9. **Zależności Pythona** — `pip install -r requirements.txt`.
10. **Sekrety** — `bootstrap_init_secrets.py` tworzy `app/secrets/` (klucze uzupełniasz ręcznie).
11. **Rejestracja roli** — `bootstrap_register.py dev`.
12. **Autostart 24/7** — `job_scheduler.py` przy logowaniu; Harmonogram zadań, a przy „Odmowa dostępu" fallback na folder Startup (pomiń: `-SkipAutostart`).
13. **Test dymny** — `bootstrap_smoke_test.py` (weryfikacja pętli).
14. **Raport stanu** — zdjęcie konfiguracji do `STAN-SRODOWISKA.txt`.

**Instalacja jest bezobsługowa** — wyzwól i możesz wrócić następnego dnia. Nie zatrzymuje się na logowaniach.

## Krok 2 (osobno, po instalacji): Logowania — `Zaloguj.bat`

Gdy środowisko jest już zainstalowane, uruchom **`Zaloguj.bat`** (dwuklik). Szybki, interaktywny przewodnik: dla każdego konta otwiera aplikację/stronę i pyta, czy zalogowane. Robisz to raz.

Po zakończeniu: uzupełnij klucze w `app/secrets/.env`. Agent startuje sam przy następnym logowaniu (krok 12 instalacji); od ręki: `python app/job_scheduler.py`. Podgląd: `python app/dashboard.py`.

## Checklist logowań (co obejmuje `Zaloguj.bat`)

Dwa profile: **konto CHMUROWE (firmowe)** i **konto PERSONALNE**. Nie wszystko robi się przez API — część pracy idzie przez interfejs, dlatego potrzebne są też logowania w przeglądarce.

| Konto | Po co | Jak |
|---|---|---|
| Claude Code (CLI) | główny model agenta | `claude` w terminalu → zaloguj subskrypcję |
| VS Code — chmurowe | główny profil pracy | VS Code → Accounts → Sign in (Microsoft 365) |
| VS Code — personalne | Settings Sync / GitHub | drugie konto w Accounts |
| Microsoft 365 | mail, SharePoint, OneDrive | office.com |
| Office (Excel/Word) — aktywacja | licencja pakietu (Business Standard) | otwórz Excel/Word → zaloguj |
| Gmail / Google | praca przez interfejs, nie tylko API | accounts.google.com |
| Meta Business | kampanie i zmiany przez interfejs | business.facebook.com |
| GitHub | repozytoria stron | github.com + VS Code |

Stan zapisywany w `app/runs/logins_status.json`.

## Uruchomienia pojedynczych kroków

Wszystko działa też osobno (folder `app/`):

```powershell
powershell -ExecutionPolicy Bypass -File app\bootstrap_install_vscode.ps1
powershell -ExecutionPolicy Bypass -File app\bootstrap_install_office.ps1     # Excel/Word (bez logowania)
powershell -ExecutionPolicy Bypass -File app\bootstrap_setup_onedrive.ps1
powershell -ExecutionPolicy Bypass -File app\bootstrap_logins.ps1            # -NonInteractive = tylko lista
powershell -ExecutionPolicy Bypass -File app\bootstrap_env_report.ps1        # mini-raport stanu maszyny
```

## Mini-info: jak jest skonfigurowana ta maszyna

`STAN-SRODOWISKA.txt` (generowany przez krok 9 / `bootstrap_env_report.ps1`) to punkt odniesienia: wersje narzędzi, rozszerzenie VS Code, modele Ollama, status OneDrive i potwierdzone logowania. Bierzesz go na nową maszynę jako wzorzec.
