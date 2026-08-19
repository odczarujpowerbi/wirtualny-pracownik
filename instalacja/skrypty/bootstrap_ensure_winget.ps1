# Best-effort instalacja winget (App Installer) - potrzebny do instalacji
# aplikacji i Terminala. Na Windows Server winget CZESTO NIE JEST domyslnie
# obecny (realnie napotkane na VM: "winget niedostepny" -> aplikacje i Terminal
# sie nie zainstalowaly). Ten krok probuje go doinstalowac; gdy sie nie uda,
# daje jasny komunikat (kolejne kroki i tak degraduja sie lagodnie).
#
# Metoda: pobranie i Add-AppxPackage:
#   - VCLibs (zaleznosc),
#   - Microsoft.UI.Xaml (zaleznosc),
#   - Microsoft.DesktopAppInstaller (winget) z https://aka.ms/getwinget.
# UWAGA: NIETESTOWANE na czystym Windows Server w tej sesji - na Server bywa
# oporne (brak wsparcia Appx bez odpowiednich funkcji). Best-effort, non-fatal.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_ensure_winget.ps1
$ErrorActionPreference = "Continue"

Write-Host "=== winget (App Installer) ==="

if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "winget juz jest - pomijam."
    exit 0
}

Write-Host "winget niedostepny - probuje doinstalowac (best-effort)..."
$tmp = Join-Path $env:TEMP "winget-setup"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @(
    @{ Name = "VCLibs";  Url = "https://aka.ms/Microsoft.VCLibs.x64.14.00.Desktop.appx"; File = "vclibs.appx" },
    @{ Name = "UI.Xaml"; Url = "https://github.com/microsoft/microsoft-ui-xaml/releases/download/v2.8.6/Microsoft.UI.Xaml.2.8.x64.appx"; File = "uixaml.appx" },
    @{ Name = "AppInstaller"; Url = "https://aka.ms/getwinget"; File = "winget.msixbundle" }
)

$ok = $true
foreach ($d in $downloads) {
    $path = Join-Path $tmp $d.File
    try {
        Write-Host "  pobieram $($d.Name)..."
        Invoke-WebRequest -Uri $d.Url -OutFile $path -UseBasicParsing
        Write-Host "  instaluje $($d.Name)..."
        Add-AppxPackage -Path $path -ErrorAction Stop
    } catch {
        Write-Host "  UWAGA: $($d.Name) nie powiodlo sie ($($_.Exception.Message))"
        # VCLibs/UI.Xaml moga juz byc obecne - to nie musi byc blokada; liczy sie winget na koncu.
        if ($d.Name -eq "AppInstaller") { $ok = $false }
    }
}

# Odswiez PATH i sprawdz efekt.
$env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "winget zainstalowany poprawnie." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "[UWAGA] Nie udalo sie doinstalowac winget automatycznie (typowe na Windows Server)."
Write-Host "Aplikacje i Terminal moga nie zainstalowac sie automatycznie. Opcje:"
Write-Host "  - zainstaluj App Installer ze Sklepu Microsoft (jesli Sklep jest dostepny), albo"
Write-Host "  - zainstaluj aplikacje recznie z bezposrednich linkow (Power BI, Chrome, Obsidian, Terminal z GitHub)."
# Non-fatal: exit 0, zeby nie przerywac calego instalatora (kolejne kroki degraduja sie same).
exit 0
