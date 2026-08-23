# Instalacja zaleznosci workera przegladarkowego (app/browser_worker.py, Faza 3.1
# z PLAN-VM.md): pakiet Playwright + binarka Chromium. Bez tego browser_worker.py
# dziala (nie wywala petli), ale zwraca available=False — patrz app/README.md.
#
# Krok OPCJONALNY w bootstrap_all.ps1 (przelacznik -WithBrowserWorker), bo to
# dodatkowe ~150-300 MB pobierania (sama binarka Chromium). Mozna tez uruchomic
# ten skrypt samodzielnie, kiedykolwiek, na juz dzialajacej maszynie.
#
# Uzycie:
#   .\bootstrap_install_browser_worker.ps1
#   .\bootstrap_install_browser_worker.ps1 -AppPath "C:\AIWorker\wirtualny-pracownik\app"

param(
    # Folder app/ z requirements.txt — domyslnie ten sam checkout, w ktorym
    # lezy ten skrypt (instalacja/skrypty/../../app).
    [string]$AppPath = (Join-Path $PSScriptRoot "..\..\app")
)

$ErrorActionPreference = "Stop"

function Test-CommandExists($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "=== Worker przegladarkowy (Playwright) ===" -ForegroundColor Cyan

if (-not (Test-CommandExists "python")) {
    Write-Error "Python nie jest zainstalowany albo nie jest w PATH. Uruchom najpierw bootstrap_install_python.ps1."
    exit 1
}

$resolvedAppPath = (Resolve-Path $AppPath -ErrorAction SilentlyContinue).Path
if (-not $resolvedAppPath) {
    Write-Error "Nie znaleziono folderu app/ pod '$AppPath'. Podaj -AppPath wskazujacy na folder z requirements.txt."
    exit 1
}

Push-Location $resolvedAppPath
try {
    # Sprawdzenie BEZ importu (find_spec) — realny `import playwright` przy braku
    # pakietu drukuje traceback na stderr, a przechwycenie stderr natywnego
    # procesu w Windows PowerShell 5.1 zamienia go w terminujacy NativeCommandError
    # (nawet z 2>$null) i wywala caly skrypt zamiast pojsc do gałęzi 'else'.
    python -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('playwright') else 1)" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Pakiet 'playwright' juz zainstalowany — pomijam pip install."
    } else {
        Write-Host "Instaluje pakiet 'playwright' (python -m pip install playwright)..."
        python -m pip install "playwright>=1.40"
        if ($LASTEXITCODE -ne 0) {
            Write-Error "Instalacja pakietu 'playwright' nie powiodla sie (kod wyjscia $LASTEXITCODE)."
            exit 1
        }
    }

    Write-Host "Instaluje binarke Chromium (playwright install chromium) — kilkaset MB, moze potrwac..."
    python -m playwright install chromium
    if ($LASTEXITCODE -ne 0) {
        Write-Error "'playwright install chromium' nie powiodlo sie (kod wyjscia $LASTEXITCODE). Sprawdz dostep do sieci — binarka pobierana jest z serwerow Playwright/CDN, nie z PyPI."
        exit 1
    }
} finally {
    Pop-Location
}

Write-Host "`nGotowe. Sprawdz dzialanie:" -ForegroundColor Green
Write-Host "  python browser_worker_smoke_test.py   # w folderze app/ — testy dymne (atrapa strony, bez sieci)"
Write-Host "  python browser_worker.py <https://adres> <host>   # realna nawigacja + zrzut"
Write-Host "`nZanim narzedzie cokolwiek zrobi na zywo, dopisz docelowa domene do:"
Write-Host "  app/config/tool_contracts.yaml -> tools.browser_task.allowed_domains (pusta na start, celowo)"
