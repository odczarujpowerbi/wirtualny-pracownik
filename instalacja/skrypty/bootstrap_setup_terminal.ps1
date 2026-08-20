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
    [string]$AppPath = (Join-Path $PSScriptRoot "..\..\app"),
    [string]$FragmentDir = (Join-Path $env:LOCALAPPDATA "Microsoft\Windows Terminal\Fragments\WirtualnyPracownik")
)
$ErrorActionPreference = "Stop"

function Install-TerminalFromGitHub {
    # Windows Server 2022 nie ma Sklepu ani (domyslnie) winget, a Terminal nie jest
    # wbudowany. Instalujemy recznie: zaleznosci (VCLibs Desktop + Microsoft.UI.Xaml)
    # oraz najnowszy .msixbundle z GitHub Releases (microsoft/terminal), przez Add-AppxPackage.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $tmp = Join-Path $env:TEMP "wt-install"
    New-Item -ItemType Directory -Path $tmp -Force | Out-Null
    $ua = @{ "User-Agent" = "wirtualny-pracownik-bootstrap" }
    $deps = @()

    # Zaleznosc 1: VCLibs Desktop (oficjalny link aka.ms).
    $vclibs = Join-Path $tmp "Microsoft.VCLibs.x64.14.00.Desktop.appx"
    Write-Host "Pobieram zaleznosc VCLibs..."
    Invoke-WebRequest -Uri "https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx" -OutFile $vclibs -UseBasicParsing
    $deps += $vclibs

    # Zaleznosc 2 (best-effort): Microsoft.UI.Xaml.2.8 - nowsze wersje Terminala jej
    # wymagaja. Pakiet nuget to zip; wyciagamy appx x64. Gdy sie nie uda, lecimy dalej
    # z sama VCLibs (starsze bundlee wystarczaja).
    try {
        $nupkg = Join-Path $tmp "muxaml.zip"
        Write-Host "Pobieram zaleznosc Microsoft.UI.Xaml.2.8..."
        Invoke-WebRequest -Uri "https://www.nuget.org/api/v2/package/Microsoft.UI.Xaml/2.8.6" -OutFile $nupkg -UseBasicParsing
        $muxDir = Join-Path $tmp "muxaml"
        if (Test-Path $muxDir) { Remove-Item $muxDir -Recurse -Force }
        Expand-Archive -Path $nupkg -DestinationPath $muxDir -Force
        $muxAppx = Join-Path $muxDir "tools\AppX\x64\Release\Microsoft.UI.Xaml.2.8.appx"
        if (Test-Path $muxAppx) { $deps += $muxAppx }
    } catch {
        Write-Host "  (Microsoft.UI.Xaml pominiete: $($_.Exception.Message))"
    }

    # Najnowszy Terminal (.msixbundle) z GitHub Releases (API wymaga naglowka User-Agent).
    Write-Host "Szukam najnowszego wydania Terminala na GitHub..."
    $rel = Invoke-RestMethod -Uri "https://api.github.com/repos/microsoft/terminal/releases/latest" -Headers $ua -UseBasicParsing
    $asset = $rel.assets | Where-Object { $_.name -like "*.msixbundle" } | Select-Object -First 1
    if (-not $asset) { throw "Nie znalazlem pliku .msixbundle w najnowszym wydaniu microsoft/terminal." }
    $bundle = Join-Path $tmp $asset.name
    Write-Host "Pobieram $($asset.name)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $bundle -UseBasicParsing

    Write-Host "Instaluje Terminal (Add-AppxPackage, zaleznosci: $($deps.Count))..."
    Add-AppxPackage -Path $bundle -DependencyPath $deps
    Write-Host "Terminal zainstalowany."
}

Write-Host "=== Terminal Windows: instalacja + konfiguracja pod Claude ==="

# 1. Instalacja, jesli brak (idempotentny). Kolejnosc: winget (gdy jest) -> bezposredni
#    MSIX + zaleznosci z GitHub Releases (Windows Server 2022: brak Sklepu i winget).
$installed = (Get-Command wt -ErrorAction SilentlyContinue) -or
             (Get-AppxPackage -Name "Microsoft.WindowsTerminal" -ErrorAction SilentlyContinue)
if ($installed) {
    Write-Host "Terminal Windows juz jest - pomijam instalacje."
} elseif (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Instaluje Terminal Windows (winget)..."
    winget install -e --id Microsoft.WindowsTerminal --accept-source-agreements --accept-package-agreements --disable-interactivity
} else {
    Write-Host "winget/Sklep niedostepne (typowe na Windows Server 2022) - instaluje Terminal bezposrednio z GitHub Releases..."
    try {
        Install-TerminalFromGitHub
    } catch {
        Write-Host "UWAGA: bezposrednia instalacja Terminala nie powiodla sie: $($_.Exception.Message)"
        Write-Host "Konfiguracja profili i tak zostanie zapisana; Terminal doinstalujesz pozniej recznie (MSIX + VCLibs z GitHub)."
    }
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
