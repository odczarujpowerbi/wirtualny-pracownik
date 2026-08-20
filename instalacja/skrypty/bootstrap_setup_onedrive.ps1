# Przygotowanie OneDrive: wykrycie klienta, uruchomienie i naprowadzenie na
# zalogowanie + sync. OneDrive to sposob, w jaki na te maszyne trafiaja projekty
# stron (te same repo co GitHub) i biblioteka skilli - patrz integrations.yaml
# (wpis onedrive) i ZESPOL-BOTOW.md sekcja 4. Bez zalogowanego OneDrive agent nie
# ma lokalnej kopii repozytoriow do pracy nad strona.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_setup_onedrive.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== OneDrive (lokalny sync projektow i skilli) ==="

# 1. Czy klient OneDrive w ogole jest (Win11 ma go domyslnie; Windows Server - nie).
function Find-OneDrive {
    @(
        (Join-Path $env:LOCALAPPDATA "Microsoft\OneDrive\OneDrive.exe"),
        "$env:ProgramFiles\Microsoft OneDrive\OneDrive.exe",
        "${env:ProgramFiles(x86)}\Microsoft OneDrive\OneDrive.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}

$onedriveExe = Find-OneDrive
if (-not $onedriveExe) {
    Write-Host "OneDrive nie znaleziony. Instaluje..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Microsoft.OneDrive --accept-source-agreements --accept-package-agreements
    } else {
        # Windows Server 2022: brak winget/Sklepu - pobieramy oficjalny instalator
        # (stabilny fwlink -> OneDriveSetup.exe) i instalujemy cicho.
        Write-Host "winget niedostepny (typowe na Windows Server 2022) - pobieram instalator OneDrive bezposrednio..."
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $od = Join-Path $env:TEMP "OneDriveSetup.exe"
            Invoke-WebRequest -Uri "https://go.microsoft.com/fwlink/?linkid=844652" -OutFile $od -UseBasicParsing
            Start-Process -FilePath $od -ArgumentList "/silent" -Wait
            Write-Host "OneDrive zainstalowany (cicho)."
        } catch {
            Write-Host "UWAGA: automatyczna instalacja OneDrive nie powiodla sie: $($_.Exception.Message)"
            Write-Host "Zainstaluj recznie: https://www.microsoft.com/microsoft-365/onedrive/download"
        }
    }
    $onedriveExe = Find-OneDrive   # po instalacji sprobuj wykryc ponownie (do kroku 2)
} else {
    Write-Host "OneDrive znaleziony: $onedriveExe"
}

# 2. Czy sync jest juz aktywny (folder $env:OneDrive ustawiony przez klienta).
if ($env:OneDrive -and (Test-Path $env:OneDrive)) {
    Write-Host "OneDrive zsynchronizowany. Folder: $env:OneDrive"
} else {
    Write-Host ""
    Write-Host ">>> DZIALANIE RECZNE: zaloguj sie do OneDrive na KONCIE FIRMOWYM (chmura)."
    Write-Host "    Otwieram klienta OneDrive - w oknie podaj adres konta firmowego i zaloguj."
    if ($onedriveExe) { Start-Process $onedriveExe }
    Write-Host "    Po zalogowaniu poczekaj, az folder projektow sie zsynchronizuje."
}

Write-Host "Krok OneDrive zakonczony."
exit 0
