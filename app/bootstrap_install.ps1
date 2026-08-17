# Krok 1-2 bootstrapu (SKALOWANIE.md sekcja 4): przygotowanie systemu i
# instalacja zależności. Uruchamiane raz, ręcznie, na nowym komputerze
# Windows, jako administrator.
#
# TESTOWANE: uruchomione naprawdę pod PowerShell Core (pwsh) 7.4.6 w tej
# sesji (z -SkipSystemChecks, bo Get-CimInstance/powercfg są Windows-only)
# — złapało i naprawiło dwa realne błędy: (1) sprawdzenie "czy już
# zainstalowano" patrzyło na zły folder i przy DRUGIM uruchomieniu zawsze
# próbowało klonować od nowa w niepusty folder, co się wywalało; (2) błąd
# `git clone`/`pip install` NIE zatrzymywał skryptu (ErrorActionPreference
# = Stop działa na cmdlety, nie na programy zewnętrzne) — skrypt kończył
# się fałszywym "Gotowe" nawet gdy klonowanie realnie się nie powiodło.
# Nieprzetestowane pozostają tylko fragmenty specyficzne dla prawdziwego
# Windows (Get-CimInstance, powercfg, sprawdzenie roli administratora) —
# sprawdź je przy pierwszym realnym uruchomieniu.
#
# Użycie (PowerShell jako administrator; -RepoUrl opcjonalny — domyślnie repo
# projektu):
#   .\bootstrap_install.ps1
#   .\bootstrap_install.ps1 -RepoUrl "https://github.com/<org>/<repo>.git"

param(
    # Repozytorium projektu — jedno miejsce do zmiany. Trzymaj zgodne z
    # config/repo.yaml (ten skrypt działa PRZED klonem, nie może go wczytać).
    [string]$RepoUrl = "https://github.com/odczarujpowerbi/wirtualny-pracownik.git",

    [string]$InstallPath = "C:\AIWorker",

    [string]$Branch = "main",

    [switch]$SkipSystemChecks
)

$ErrorActionPreference = "Stop"

Write-Host "=== 1. Sprawdzenie systemu ===" -ForegroundColor Cyan

if (-not $SkipSystemChecks) {
    $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    if (-not $isAdmin) {
        Write-Warning "Ten skrypt nie jest uruchomiony jako Administrator — zmiana ustawień uśpienia (powercfg) niżej może się nie powieść po cichu. Zamknij i uruchom PowerShell przez 'Uruchom jako administrator'."
    }

    $ram_gb = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 1)
    Write-Host "RAM: $ram_gb GB"
    if ($ram_gb -lt 16) {
        Write-Warning "RAM poniżej zalecanego minimum 16 GB (dokumentacja bazowa rozdz. 4.1) dla docelowej, produkcyjnej maszyny. Do testowania mechanizmu (bez Power BI Desktop) to nie przeszkadza — kontynuuję."
    }

    $productType = (Get-CimInstance Win32_OperatingSystem).ProductType
    if ($productType -ne 1) {
        Write-Warning "Wykryto Windows Server (nie edycję desktopową). Power BI Desktop NIE jest oficjalnie wspierany przez Microsoft na Windows Server — może działać niestabilnie albo wcale. To NIE blokuje testowania samego mechanizmu (runner/Projectly/raporty), dotyczy dopiero przyszłego kroku ze zrzutami PBIP (PBI-01/02, patrz app/README.md)."
    }

    # Wyłączenie uśpienia/hibernacji — dedykowany komputer ma działać 24/7.
    powercfg /change standby-timeout-ac 0
    powercfg /change hibernate-timeout-ac 0
    Write-Host "Uśpienie i hibernacja wyłączone (zasilanie z sieci)."
}

Write-Host "=== 2. Instalacja zależności ===" -ForegroundColor Cyan

function Test-CommandExists($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

function Test-PythonWorks {
    # Samo Get-Command nie wystarczy: na czystym Windows "python" bez
    # zainstalowanego Pythona bywa aliasem do Microsoft Store (otwiera
    # sklep zamiast dać błąd) — sprawdzamy więc realne wyjście polecenia.
    try {
        $output = & python --version 2>&1
        return ($LASTEXITCODE -eq 0) -and ($output -match "Python 3")
    } catch {
        return $false
    }
}

if (-not (Test-CommandExists "git")) {
    Write-Error "Git nie jest zainstalowany (typowe na świeżej maszynie wirtualnej/Windows Server). Zainstaluj z https://git-scm.com/download/win, albo uruchom .\bootstrap_install_git.ps1 z tego samego folderu (instaluje automatycznie), a potem uruchom ten skrypt ponownie."
    exit 1
}

if (-not (Test-PythonWorks)) {
    Write-Error "Python nie jest zainstalowany (albo 'python' otwiera Microsoft Store zamiast prawdziwego Pythona). Zainstaluj Python 3.11+ z https://www.python.org/downloads/windows/ (zaznacz 'Add to PATH') i uruchom ten skrypt ponownie."
    exit 1
}

Write-Host "Git i Python znalezione."

Write-Host "=== 3. Klonowanie rdzenia (kod, ten sam dla każdego wdrożenia) ===" -ForegroundColor Cyan

# Repo ma kod w korzeniu — klonujemy do podfolderu wirtualny-pracownik/, żeby
# lokalny układ to nadal $InstallPath\wirtualny-pracownik\app.
$repoDir = Join-Path $InstallPath "wirtualny-pracownik"
$appPath = Join-Path $repoDir "app"
if (Test-Path (Join-Path $repoDir ".git")) {
    # Repo już jest — ZAWSZE nadpisujemy kod do stanu zdalnego (origin/$Branch),
    # zamiast pomijać. reset --hard rusza TYLKO pliki wersjonowane, więc secrets/
    # i runs/ (w .gitignore) zostają nietknięte — ponowny bootstrap nie kasuje
    # Twoich sekretów ani stanu lokalnego.
    Write-Host "$repoDir już istnieje — nadpisuję kod do origin/$Branch (secrets/ i runs/ zostają)."
    git -C $repoDir remote set-url origin $RepoUrl
    git -C $repoDir fetch origin $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git fetch nie powiodło się (kod $LASTEXITCODE). Sprawdź adres repozytorium i dostęp do sieci."
        exit 1
    }
    git -C $repoDir reset --hard "origin/$Branch"
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git reset --hard nie powiodło się (kod $LASTEXITCODE)."
        exit 1
    }
} else {
    if (Test-Path $repoDir) {
        # Folder istnieje, ale to NIE repozytorium git (niepełna/uszkodzona kopia)
        # — usuwamy i klonujemy świeżo.
        Write-Warning "$repoDir istnieje, ale to nie repozytorium git — usuwam i klonuję świeżo."
        Remove-Item $repoDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $InstallPath -Force | Out-Null
    git clone --branch $Branch $RepoUrl $repoDir
    if ($LASTEXITCODE -ne 0) {
        Write-Error "git clone nie powiodło się (kod wyjścia $LASTEXITCODE). Sprawdź adres repozytorium, nazwę gałęzi ('$Branch') i dostęp do sieci — skrypt zatrzymany, żeby nie kontynuować na niepełnej kopii."
        exit 1
    }
    if (-not (Test-Path $appPath)) {
        Write-Error "Klon się powiódł, ale $appPath nie istnieje. Sprawdź, czy to właściwe repozytorium (kod projektu ma być w korzeniu repo, w folderze app/)."
        exit 1
    }
}

Write-Host "=== 4. Instalacja zależności Python ===" -ForegroundColor Cyan
Push-Location $appPath
try {
    python -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Aktualizacja pip nie powiodła się (kod wyjścia $LASTEXITCODE) — zwykle nieszkodliwe, kontynuuję instalację zależności."
    }

    python -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Instalacja zależności z requirements.txt nie powiodła się (kod wyjścia $LASTEXITCODE)."
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host "`n=== Gotowe ===" -ForegroundColor Green
Write-Host "Dalsze kroki (SKALOWANIE.md sekcja 4, punkty 3-9):"
Write-Host "  1. Utwórz dedykowane konto standardowe dla bota (osobne od administratora)."
Write-Host "  2. Ustaw zmienne środowiskowe: ANTHROPIC_API_KEY, PROJECTLY_API_KEY, PROJECTLY_BASE_URL."
Write-Host "  3. Uruchom: python bootstrap_register.py <rola>"
Write-Host "  4. Uruchom: python bootstrap_smoke_test.py"
Write-Host "  5. Zarejestruj runner_loop.py w Harmonogramie zadań Windows (uruchamianie przy starcie systemu)."
