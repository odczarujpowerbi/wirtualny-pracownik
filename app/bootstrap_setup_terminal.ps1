# Terminal Windows: instalacja (jesli brak) + KONFIGURACJA profili pod Claude.
#
# Konfiguracja przez FRAGMENT Windows Terminal (osobny plik JSON, ktory WT sam
# wczytuje) - niedestrukcyjne: DODAJE profile, nie nadpisujac ustawien uzytkownika.
# Dodaje dwa profile widoczne w rozwijanym menu Terminala:
#   1. "Wirtualny Pracownik" - otwiera PowerShell w katalogu projektu (app/).
#   2. "Claude - Wirtualny Pracownik" - od razu odpala Claude Code (claude) w app/.
#
# Idempotentne: nadpisuje wlasny fragment. Nie zmienia domyslnego profilu
# (szanujemy ustawienia uzytkownika) - jak chcesz Claude jako domyslny, ustaw
# w Terminal -> Ustawienia -> Domyslny profil.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:
#   powershell -ExecutionPolicy Bypass -File bootstrap_setup_terminal.ps1
#   ... -AppPath <sciezka app>   ... -FragmentDir <sciezka>   (do testow)
param(
    [string]$AppPath = $PSScriptRoot,
    [string]$FragmentDir = (Join-Path $env:LOCALAPPDATA "Microsoft\Windows Terminal\Fragments\WirtualnyPracownik")
)
$ErrorActionPreference = "Stop"

Write-Host "=== Terminal Windows: instalacja + konfiguracja pod Claude ==="

# 1. Instalacja, jesli brak (winget, idempotentny).
$installed = (Get-Command wt -ErrorAction SilentlyContinue) -or
             (Get-AppxPackage -Name "Microsoft.WindowsTerminal" -ErrorAction SilentlyContinue)
if ($installed) {
    Write-Host "Terminal Windows juz jest - pomijam instalacje."
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Instaluje Terminal Windows (winget)..."
    winget install -e --id Microsoft.WindowsTerminal --accept-source-agreements --accept-package-agreements --disable-interactivity
} else {
    Write-Host "UWAGA: winget niedostepny - zainstaluj Terminal ze Sklepu, potem uruchom ten skrypt ponownie dla konfiguracji."
}

# 2. Fragment z profilami. Budujemy przez hashtable -> ConvertTo-Json (poprawny JSON).
#    -NoExit zostawia okno otwarte po komendzie. cd w app/, potem (dla Claude) claude.
$appEsc = $AppPath.Replace("'", "''")   # bezpieczne w PowerShell -Command
$fragment = @{
    profiles = @(
        @{
            name              = "Wirtualny Pracownik"
            commandline       = "powershell.exe -NoExit -Command ""Set-Location -LiteralPath '$appEsc'"""
            startingDirectory = $AppPath
        },
        @{
            name              = "Claude - Wirtualny Pracownik"
            commandline       = "powershell.exe -NoExit -Command ""Set-Location -LiteralPath '$appEsc'; claude"""
            startingDirectory = $AppPath
        }
    )
}

New-Item -ItemType Directory -Path $FragmentDir -Force | Out-Null
$fragmentPath = Join-Path $FragmentDir "profiles.json"
$fragment | ConvertTo-Json -Depth 6 | Set-Content -Path $fragmentPath -Encoding UTF8

Write-Host "Zapisano fragment profili: $fragmentPath"
Write-Host "Po (ponownym) uruchomieniu Terminala zobaczysz w menu: 'Wirtualny Pracownik' i 'Claude - Wirtualny Pracownik'."
exit 0
