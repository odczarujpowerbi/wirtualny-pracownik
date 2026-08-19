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

# 1. Czy klient OneDrive w ogole jest (Win11 ma go domyslnie).
$onedriveExe = @(
    (Join-Path $env:LOCALAPPDATA "Microsoft\OneDrive\OneDrive.exe"),
    "$env:ProgramFiles\Microsoft OneDrive\OneDrive.exe",
    "${env:ProgramFiles(x86)}\Microsoft OneDrive\OneDrive.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $onedriveExe) {
    Write-Host "OneDrive nie znaleziony. Instaluje..."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install -e --id Microsoft.OneDrive --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "UWAGA: winget niedostepny. Zainstaluj OneDrive recznie: https://www.microsoft.com/microsoft-365/onedrive/download"
    }
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
