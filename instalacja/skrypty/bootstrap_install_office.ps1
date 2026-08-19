# Instaluje pakiet Microsoft Office / Microsoft 365 Apps (Excel, Word, PowerPoint...).
# Idempotentne: jesli Office juz jest (ClickToRun albo Excel/Word na dysku), pomija.
#
# DLACZEGO: agent ma pracowac na Excelu/Wordzie dwiema drogami - przez MCP do
# Excela (operacje na plikach/arkuszach) oraz przez boty czytajace ekran
# (computer use) dla rzeczy, ktorych nie da sie zrobic przez API. Bez lokalnego
# Office ani jedno, ani drugie nie ma na czym pracowac.
#
# JAK: preferujemy DOLACZONY instalator w repo (instalacja/office/OfficeSetup.exe),
# a dopiero gdy go brak - winget, a na koncu instrukcja reczna. Dolaczony to
# oficjalny stub Click-to-Run (~7 MB) - i tak dociaga pakiet z serwerow MS, ale
# nie wymaga winget na kazdej maszynie.
#
# LOGOWANIE: instalator POBIERA I INSTALUJE pakiet BEZ konta. Logowanie (konto
# Microsoft 365 Business Standard) potrzebne dopiero do AKTYWACJI licencji -
# krok w bootstrap_logins.ps1 (docelowo aktywacje moze przejac agent computer-use).
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

# Priorytet 1: DOLACZONY instalator w repo (instalacja/office/OfficeSetup.exe).
# To oficjalny stub Click-to-Run - pobiera i instaluje BEZ logowania; aktywacja
# licencji pozniej kontem Business Standard. Wrzucony do repo, zeby nie polegac
# na winget na kazdej maszynie.
# WAZNE: Office (Click-to-Run) instaluje sie WLASNA usluga w tle
# (OfficeClickToRun.exe). Uruchamiamy instalator ASYNCHRONICZNIE (bez -Wait) i
# NIE blokujemy reszty instalacji - pobieranie kilku GB toczy sie samo w tle,
# a orkiestrator leci dalej z kolejnymi aplikacjami. Aktywacja licencji (konto
# Business Standard) to i tak osobny, pozniejszy krok.
$bundled = Join-Path $PSScriptRoot "..\office\OfficeSetup.exe"
if (Test-Path $bundled) {
    Write-Host "Uruchamiam dolaczony instalator W TLE: $bundled"
    Start-Process -FilePath $bundled
    Write-Host "Office instaluje sie w tle (usluga Click-to-Run). Kontynuuje reszte instalacji."
    Write-Host "PO ZAKONCZENIU (w tle): zaloguj sie kontem Business Standard w Excelu/Wordzie, zeby aktywowac licencje."
    exit 0
}

# Priorytet 2: winget (Microsoft.Office = Microsoft 365 Apps), tez asynchronicznie.
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Brak dolaczonego instalatora - uruchamiam winget W TLE."
    Start-Process -FilePath "winget" -ArgumentList @(
        "install", "-e", "--id", "Microsoft.Office",
        "--accept-source-agreements", "--accept-package-agreements"
    )
    Write-Host "Office instaluje sie w tle przez winget. Kontynuuje reszte instalacji."
    Write-Host "PO ZAKONCZENIU: zaloguj sie kontem Business Standard, zeby aktywowac licencje."
    exit 0
}

# Priorytet 3: instrukcja reczna.
Write-Host "UWAGA: brak dolaczonego instalatora i winget. Zainstaluj Office recznie:"
Write-Host "  - portal: https://portal.office.com -> zaloguj Business Standard -> Zainstaluj aplikacje, ALBO"
Write-Host "  - Office Deployment Tool: https://aka.ms/ODT (konfiguracja XML + setup.exe /download /configure)"
exit 1
