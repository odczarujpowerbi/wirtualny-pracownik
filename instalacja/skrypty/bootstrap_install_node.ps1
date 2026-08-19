# Instaluje Node.js (LTS). Potrzebny do statuslinii Claude (npx claude-powerline)
# i ogolnie do narzedzi npm. Idempotentny: jesli 'node' juz jest - pomija.
#
# WAZNE: na Windows Server winget czesto NIE JEST dostepny, dlatego glowna
# sciezka to BEZPOSREDNI instalator MSI z nodejs.org (nie winget). winget
# probujemy tylko jesli jest.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_install_node.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== Node.js (dla statuslinii Claude / npx) ==="

if (Get-Command node -ErrorAction SilentlyContinue) {
    Write-Host "Node.js juz jest: $(node --version) - pomijam."
    exit 0
}

# Sciezka 1: winget (jesli dostepny).
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Instaluje Node.js LTS przez winget..."
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements --disable-interactivity
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    if (Get-Command node -ErrorAction SilentlyContinue) { Write-Host "Node.js zainstalowany: $(node --version)" -ForegroundColor Green; exit 0 }
    Write-Host "winget nie dokonczyl - probuje bezposredni MSI..."
}

# Sciezka 2: bezposredni MSI z nodejs.org (dziala bez winget/Sklepu - wazne na Server).
$ver = "v22.11.0"   # LTS; do podbicia recznie przy aktualizacji
$msi = Join-Path $env:TEMP "node-lts-x64.msi"
$url = "https://nodejs.org/dist/$ver/node-$ver-x64.msi"
try {
    Write-Host "Pobieram Node.js $ver MSI..."
    Invoke-WebRequest -Uri $url -OutFile $msi -UseBasicParsing
    Write-Host "Instaluje (cicho)..."
    Start-Process msiexec.exe -ArgumentList "/i", "`"$msi`"", "/qn", "/norestart" -Wait
    $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User")
    if (Get-Command node -ErrorAction SilentlyContinue) {
        Write-Host "Node.js zainstalowany: $(node --version)" -ForegroundColor Green
        exit 0
    }
    Write-Host "UWAGA: instalacja MSI zakonczona, ale 'node' nie w PATH tej sesji - otworz nowy terminal."
    exit 0
} catch {
    Write-Host "UWAGA: nie udalo sie zainstalowac Node.js ($($_.Exception.Message))."
    Write-Host "Statuslinia Claude (npx) nie zadziala bez Node. Zainstaluj recznie: https://nodejs.org (LTS)."
    exit 1
}
