# POSTAW OD ZERA - dla calkowicie pustej maszyny (nic nie ma: ani repo, ani git).
# Pobiera gita, klonuje repozytorium i uruchamia pelny instalator srodowiska
# (VS Code, Office, modele lokalne, OneDrive, zaleznosci, logowania, sekrety,
# rejestracja roli, test dymny, raport). Jeden strzal od czystego Windows do
# dzialajacego narzedzia.
#
# Uruchomienie na czystej maszynie (PowerShell jako ADMINISTRATOR):
#   $s="$env:TEMP\postaw.ps1"; irm https://raw.githubusercontent.com/odczarujpowerbi/wirtualny-pracownik/main/instalacja/postaw-od-zera.ps1 -OutFile $s; powershell -ExecutionPolicy Bypass -File $s
#
# Opcje: -InstallPath, -RepoUrl, -Branch, -SkipOffice, -SkipLocalModel, -SkipLogins
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
param(
    [string]$RepoUrl = "https://github.com/odczarujpowerbi/wirtualny-pracownik.git",
    [string]$InstallPath = "$env:USERPROFILE\wirtualny-pracownik",
    [string]$Branch = "main",
    [switch]$SkipOffice,
    [switch]$SkipApps,
    [switch]$SkipTerminal,
    [switch]$SkipLocalModel,
    [switch]$SkipAutostart
)
$ErrorActionPreference = "Stop"

function Test-Command($name) { return [bool](Get-Command $name -ErrorAction SilentlyContinue) }

function Update-PathFromRegistry {
    # Po instalacji przez winget nowe narzedzia trafiaja do PATH w rejestrze, ale
    # NIE do biezacej sesji. Odswiezamy $env:Path, zeby 'git' byl widoczny od razu.
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

function Install-GitDirect {
    # Bezposrednia instalacja Git dla Windows (bez winget) - dla czystego Windows
    # Server 2022, gdzie winget czesto nie istnieje. Pobiera najnowszy oficjalny
    # instalator git-for-windows z GitHub Releases i instaluje cicho. Ta sama
    # metoda co bootstrap_install_git.ps1 (tam nieuzywalne tutaj, bo repo nie jest
    # jeszcze sklonowane - git jest potrzebny wlasnie do klonowania).
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Write-Host "Pobieram najnowszy instalator Git dla Windows z GitHub..."
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/git-for-windows/git/releases/latest" -Headers @{ "User-Agent" = "wirtualny-pracownik-bootstrap" }
    $asset = $release.assets | Where-Object { $_.name -match "^Git-.*-64-bit\.exe$" } | Select-Object -First 1
    if (-not $asset) { throw "Nie znalazlem 64-bitowego instalatora Git w najnowszym wydaniu. Zainstaluj recznie z https://git-scm.com/download/win i uruchom ponownie." }
    $installer = Join-Path $env:TEMP $asset.name
    Write-Host "Pobieram $($asset.name)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installer -UseBasicParsing
    Write-Host "Instaluje cicho (bez okienek)..."
    Start-Process -FilePath $installer -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-" -Wait
    Remove-Item $installer -ErrorAction SilentlyContinue
}

Write-Host "=== POSTAW OD ZERA - Wirtualny Pracownik AI ===" -ForegroundColor Cyan
Write-Host "Repo:    $RepoUrl ($Branch)"
Write-Host "Docelowo: $InstallPath"
Write-Host ""

# --- 1. Git (jesli brak) ---
if (-not (Test-Command "git")) {
    Write-Host "[1/3] Git nie znaleziony - instaluje..." -ForegroundColor Cyan
    if (Test-Command "winget") {
        winget install -e --id Git.Git --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "winget niedostepny (typowe na Windows Server 2022) - instaluje Git bezposrednio z GitHub..." -ForegroundColor Yellow
        Install-GitDirect
    }
    Update-PathFromRegistry
    if (-not (Test-Command "git")) {
        # Fallback: typowa sciezka instalacji gita.
        $gitCmd = "$env:ProgramFiles\Git\cmd"
        if (Test-Path $gitCmd) { $env:Path = "$gitCmd;$env:Path" }
    }
    if (-not (Test-Command "git")) { throw "Git zainstalowany, ale niewidoczny w PATH - otworz nowy terminal i uruchom ponownie." }
} else {
    Write-Host "[1/3] Git juz jest - pomijam." -ForegroundColor Green
}

# --- 2. Klon repo (albo aktualizacja, jesli juz jest) ---
if (Test-Path (Join-Path $InstallPath ".git")) {
    Write-Host "[2/3] Repo juz istnieje w $InstallPath - pobieram najnowsze (git pull)." -ForegroundColor Green
    Push-Location $InstallPath
    try { git pull --ff-only | Out-Host } finally { Pop-Location }
} else {
    Write-Host "[2/3] Klonuje repo..." -ForegroundColor Cyan
    git clone --branch $Branch $RepoUrl $InstallPath | Out-Host
}

# --- 3. Pelny instalator srodowiska (nowy proces, przekazujemy przelaczniki) ---
$orchestrator = Join-Path $InstallPath "instalacja\skrypty\przygotuj-srodowisko.ps1"
if (-not (Test-Path $orchestrator)) { throw "Brak orkiestratora: $orchestrator (czy repo sklonowalo sie poprawnie?)" }

$fwd = @()
if ($SkipOffice)     { $fwd += "-SkipOffice" }
if ($SkipApps)       { $fwd += "-SkipApps" }
if ($SkipTerminal)   { $fwd += "-SkipTerminal" }
if ($SkipLocalModel) { $fwd += "-SkipLocalModel" }
if ($SkipAutostart)  { $fwd += "-SkipAutostart" }

Write-Host "`n[3/3] Uruchamiam pelny instalator srodowiska..." -ForegroundColor Cyan
$psExe = (Get-Process -Id $PID).Path
& $psExe -NoProfile -ExecutionPolicy Bypass -File $orchestrator @fwd | Out-Host

Write-Host "`n=== GOTOWE ===" -ForegroundColor Green
Write-Host "Katalog:  $InstallPath"
Write-Host "Uzupelnij klucze:  $InstallPath\app\secrets\.env"
Write-Host "Start pętli 24/7:   cd $InstallPath\app ; python job_scheduler.py"
Write-Host "Dashboard:          cd $InstallPath\app ; python dashboard.py  -> http://127.0.0.1:8787/"
exit 0
