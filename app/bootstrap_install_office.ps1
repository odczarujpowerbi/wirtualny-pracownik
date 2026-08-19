# Instaluje pakiet Microsoft Office / Microsoft 365 Apps (Excel, Word, PowerPoint...).
# Idempotentne: jesli Office juz jest (ClickToRun albo Excel/Word na dysku), pomija.
#
# DLACZEGO: agent ma pracowac na Excelu/Wordzie dwiema drogami - przez MCP do
# Excela (operacje na plikach/arkuszach) oraz przez boty czytajace ekran
# (computer use) dla rzeczy, ktorych nie da sie zrobic przez API. Bez lokalnego
# Office ani jedno, ani drugie nie ma na czym pracowac.
#
# JAK/LOGOWANIE: instalator Click-to-Run POBIERA I INSTALUJE pakiet BEZ konta.
# Logowanie (konto Microsoft 365 Business Standard) jest potrzebne dopiero do
# AKTYWACJI licencji - robi je czlowiek pozniej (krok w bootstrap_logins.ps1).
# Po aktywacji boty korzystaja z zainstalowanych aplikacji.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_install_office.ps1
$ErrorActionPreference = "Stop"

Write-Host "=== Microsoft Office / Microsoft 365 Apps (Excel, Word, ...) ==="

function Test-OfficeInstalled {
    # 1) Konfiguracja Click-to-Run (najpewniejszy sygnal instalacji Microsoft 365).
    if (Test-Path "HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration") { return $true }
    # 2) Fallback: obecnosc EXCEL.EXE / WINWORD.EXE w typowych lokalizacjach.
    $exes = @(
        "$env:ProgramFiles\Microsoft Office\root\Office16\EXCEL.EXE",
        "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\EXCEL.EXE",
        "$env:ProgramFiles\Microsoft Office\root\Office16\WINWORD.EXE",
        "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\WINWORD.EXE"
    )
    foreach ($e in $exes) { if (Test-Path $e) { return $true } }
    return $false
}

if (Test-OfficeInstalled) {
    Write-Host "Office juz zainstalowany - pomijam pobieranie (kilka GB)."
    Write-Host "Jesli nie jest aktywowany: zaloguj sie kontem Microsoft 365 Business Standard w Excelu/Wordzie."
    exit 0
}

Write-Host "Office nie wykryty. Instaluje Microsoft 365 Apps (pobieranie kilku GB)..."
if (Get-Command winget -ErrorAction SilentlyContinue) {
    # Microsoft.Office w winget = Microsoft 365 Apps (Click-to-Run). Pobiera bez
    # logowania; aktywacja pozniej przez konto Business Standard.
    winget install -e --id Microsoft.Office --accept-source-agreements --accept-package-agreements
    if (Test-OfficeInstalled) {
        Write-Host "Office zainstalowany. NASTEPNY KROK (recznie): zaloguj sie kontem Business Standard, zeby aktywowac licencje."
        exit 0
    }
    Write-Host "UWAGA: winget zakonczyl sie, ale nie wykrywam Office - sprawdz recznie."
    exit 1
} else {
    Write-Host "UWAGA: winget niedostepny. Zainstaluj Office recznie na jeden ze sposobow:"
    Write-Host "  - portal: https://portal.office.com -> zaloguj Business Standard -> Zainstaluj aplikacje, ALBO"
    Write-Host "  - Office Deployment Tool: https://aka.ms/ODT (konfiguracja XML + setup.exe /download /configure)"
    exit 1
}
