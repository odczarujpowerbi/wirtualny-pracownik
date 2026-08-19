# Przygotowanie środowiska na nowej maszynie

Jeden klik: **`Przygotuj-srodowisko.bat`** (dwuklik). Na zupełnie świeżej maszynie kliknij prawym → *Uruchom jako administrator* (część instalatorów tego wymaga; inaczej działa per-user).

## Co robi (kolejno)

1. **Git** — wymagane.
2. **Python 3.11+** — wymagane.
3. **Claude Code (CLI)** — naped głównego modelu agenta.
4. **VS Code + rozszerzenie Claude Code** — kodowanie z agentem w edytorze (poprawki na stronie w repo).
5. **Modele lokalne (Ollama)** — tania druga opinia / computer use (kilka GB; pomiń: `-SkipLocalModel`).
6. **OneDrive** — lokalny sync projektów stron i biblioteki skilli.
7. **Zależności Pythona** — `pip install -r requirements.txt`.
8. **Logowania** — interaktywny checklist kont (patrz niżej; pomiń: `-SkipLogins`).
9. **Raport stanu** — zdjęcie konfiguracji do `STAN-SRODOWISKA.txt`.

## Checklist logowań (krok 8)

Dwa profile: **konto CHMUROWE (firmowe)** i **konto PERSONALNE**. Nie wszystko robi się przez API — część pracy idzie przez interfejs, dlatego potrzebne są też logowania w przeglądarce.

| Konto | Po co | Jak |
|---|---|---|
| Claude Code (CLI) | główny model agenta | `claude` w terminalu → zaloguj subskrypcję |
| VS Code — chmurowe | główny profil pracy | VS Code → Accounts → Sign in (Microsoft 365) |
| VS Code — personalne | Settings Sync / GitHub | drugie konto w Accounts |
| Microsoft 365 | mail, SharePoint, OneDrive | office.com |
| Gmail / Google | praca przez interfejs, nie tylko API | accounts.google.com |
| Meta Business | kampanie i zmiany przez interfejs | business.facebook.com |
| GitHub | repozytoria stron | github.com + VS Code |

Stan zapisywany w `app/runs/logins_status.json`.

## Uruchomienia pojedynczych kroków

Wszystko działa też osobno (folder `app/`):

```powershell
powershell -ExecutionPolicy Bypass -File app\bootstrap_install_vscode.ps1
powershell -ExecutionPolicy Bypass -File app\bootstrap_setup_onedrive.ps1
powershell -ExecutionPolicy Bypass -File app\bootstrap_logins.ps1            # -NonInteractive = tylko lista
powershell -ExecutionPolicy Bypass -File app\bootstrap_env_report.ps1        # mini-raport stanu maszyny
```

## Mini-info: jak jest skonfigurowana ta maszyna

`STAN-SRODOWISKA.txt` (generowany przez krok 9 / `bootstrap_env_report.ps1`) to punkt odniesienia: wersje narzędzi, rozszerzenie VS Code, modele Ollama, status OneDrive i potwierdzone logowania. Bierzesz go na nową maszynę jako wzorzec.
