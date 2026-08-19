# Instaluje Python 3.11+, jesli nie jest jeszcze na maszynie.
#
# Kolejnosc prob: (1) winget, jesli dostepny; (2) w razie braku pobranie
# oficjalnego instalatora z python.org i cicha instalacja z udokumentowanymi
# przelacznikami (https://docs.python.org/3/using/windows.html#installing-without-ui):
# InstallAllUsers=1 PrependPath=1 (dodaje do PATH automatycznie, wiec nie
# trzeba juz reczne zaznaczac "Add to PATH" w instalatorze).
#
# TESTOWANE w tej sesji pod PowerShell Core: logika wykrywania
# (Test-PythonWorks) w obu kierunkach. NIEtestowane: samo pobranie z
# python.org (zablokowane w sieci TEJ sesji budowy - potwierdzone: "gateway
# answered 403 to CONNECT, policy denial") oraz sama cicha instalacja .exe
# (Windows-only) - ograniczenia srodowiska budowy, nie kodu. Przelaczniki
# instalatora sa oficjalnie udokumentowane przez python.org, nie zgadywane.
#
# Uzycie (PowerShell, najlepiej jako Administrator):
#   .\bootstrap_install_python.ps1

$ErrorActionPreference = "Stop"

function Test-PythonWorks {
    try {
        $output = & python --version 2>&1
        return ($LASTEXITCODE -eq 0) -and ($output -match "Python 3\.(1[1-9]|[2-9][0-9])")
    } catch {
        return $false
    }
}

if (Test-PythonWorks) {
    Write-Host "Python juz jest zainstalowany: $(python --version)" -ForegroundColor Green
    exit 0
}

Write-Host "Python 3.11+ nie znaleziony - instaluje..." -ForegroundColor Cyan

$installedViaWinget = $false
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Proba przez winget..."
    winget install --id Python.Python.3.12 -e --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -eq 0) {
        $installedViaWinget = $true
    } else {
        Write-Warning "winget nie zainstalowal Pythona (kod wyjscia $LASTEXITCODE) - probuje pobrac instalator bezposrednio."
    }
} else {
    Write-Warning "winget niedostepny na tej maszynie - pobieram instalator bezposrednio z python.org."
}

if (-not $installedViaWinget) {
    # Wersja przypieta swiadomie (python.org nie ma prostego API "latest") -
    # podmien na nowsza, jesli chcesz: https://www.python.org/downloads/windows/
    $pythonVersion = "3.12.7"
    $installerUrl = "https://www.python.org/ftp/python/$pythonVersion/python-$pythonVersion-amd64.exe"
    $installerPath = Join-Path $env:TEMP "python-$pythonVersion-amd64.exe"

    Write-Host "Pobieram Python $pythonVersion..."
    try {
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath
    } catch {
        Write-Error "Pobieranie nie powiodlo sie: $_. Zainstaluj recznie z https://www.python.org/downloads/windows/ (zaznacz 'Add python.exe to PATH')."
        exit 1
    }

    Write-Host "Instaluje cicho (bez okienek), dla wszystkich uzytkownikow, z dodaniem do PATH..."
    Start-Process -FilePath $installerPath -ArgumentList "/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0" -Wait
    Remove-Item $installerPath -ErrorAction SilentlyContinue
}

# Odswiez PATH w BIEZACEJ sesji PowerShell, zeby nie trzeba bylo jej zamykac.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

if (Test-PythonWorks) {
    Write-Host "Python zainstalowany poprawnie: $(python --version)" -ForegroundColor Green
} else {
    Write-Warning "Instalacja sie zakonczyla, ale 'python' wciaz nie odpowiada w tej sesji. Zamknij to okno PowerShell, otworz nowe i sprawdz 'python --version' jeszcze raz."
}
