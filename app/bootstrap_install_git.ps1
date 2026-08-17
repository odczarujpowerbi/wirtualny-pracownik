# Instaluje Git dla Windows, jeśli nie jest jeszcze na maszynie.
#
# Dlaczego to osobny skrypt: świeża maszyna wirtualna / Windows Server
# domyślnie NIE MA gita (w odróżnieniu od komputera dewelopera, gdzie
# zwykle już jest) — to pierwsza rzecz, która wywala `bootstrap_install.ps1`
# (INSTRUKCJA-WDROZENIA.md Krok 2 / WDROZENIE-VPS-TESTOWE.md), zanim
# cokolwiek innego zdąży się uruchomić.
#
# Kolejność prób: (1) winget, jeśli jest dostępny — najprostsze; (2) w razie
# braku winget (typowe na Windows Server) pobranie najnowszego instalatora
# bezpośrednio z oficjalnych wydań git-for-windows na GitHubie i cicha
# instalacja (bez okienek, bez klikania "Dalej").
#
# TESTOWANE w tej sesji pod PowerShell Core (pwsh): funkcja Test-GitWorks
# w obu kierunkach (git jest / git nie istnieje) działa poprawnie.
# NIEtestowane: samo zapytanie do api.github.com/repos/git-for-windows/git
# (sieć w TEJ sesji budowy jest ograniczona do repozytoriów już podłączonych
# do sesji, więc nie mogłem uderzyć w cudze publiczne API GitHuba — to
# ograniczenie środowiska budowy, nie kodu; na prawdziwym Windows Server
# z normalnym dostępem do internetu zapytanie powinno przejść bez problemu,
# ale sprawdź to jako pierwsze, jeśli winget akurat zawiedzie) oraz sama
# cicha instalacja .exe (Windows-only, brak prawdziwego Windows w tej sesji).
# Jeśli automat zawiedzie w którymkolwiek miejscu — zainstaluj ręcznie z
# https://git-scm.com/download/win, to zawsze działa.
#
# Użycie (PowerShell, najlepiej jako Administrator):
#   .\bootstrap_install_git.ps1

$ErrorActionPreference = "Stop"

function Test-GitWorks {
    try {
        $output = & git --version 2>&1
        return ($LASTEXITCODE -eq 0) -and ($output -match "git version")
    } catch {
        return $false
    }
}

if (Test-GitWorks) {
    Write-Host "Git już jest zainstalowany: $(git --version)" -ForegroundColor Green
    exit 0
}

Write-Host "Git nie znaleziony — instaluję..." -ForegroundColor Cyan

$installedViaWinget = $false
if (Get-Command winget -ErrorAction SilentlyContinue) {
    Write-Host "Próba przez winget..."
    winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements --silent
    if ($LASTEXITCODE -eq 0) {
        $installedViaWinget = $true
    } else {
        Write-Warning "winget nie zainstalował gita (kod wyjścia $LASTEXITCODE) — próbuję pobrać instalator bezpośrednio."
    }
} else {
    Write-Warning "winget niedostępny na tej maszynie (typowe dla Windows Server) — pobieram instalator bezpośrednio z GitHuba."
}

if (-not $installedViaWinget) {
    Write-Host "Sprawdzanie najnowszego wydania Git dla Windows..."
    $release = Invoke-RestMethod -Uri "https://api.github.com/repos/git-for-windows/git/releases/latest" -Headers @{ "User-Agent" = "wirtualny-pracownik-bootstrap" }
    $asset = $release.assets | Where-Object { $_.name -match "^Git-.*-64-bit\.exe$" } | Select-Object -First 1
    if (-not $asset) {
        Write-Error "Nie znaleziono 64-bitowego instalatora w najnowszym wydaniu. Zainstaluj ręcznie z https://git-scm.com/download/win i uruchom ten skrypt ponownie (albo od razu bootstrap_install.ps1)."
        exit 1
    }

    $installerPath = Join-Path $env:TEMP $asset.name
    Write-Host "Pobieram $($asset.name)..."
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $installerPath

    Write-Host "Instaluję cicho (bez okienek, bez klikania)..."
    Start-Process -FilePath $installerPath -ArgumentList "/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-" -Wait
    Remove-Item $installerPath -ErrorAction SilentlyContinue
}

# Odśwież PATH w BIEŻĄCEJ sesji PowerShell, żeby nie trzeba było jej zamykać.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

if (Test-GitWorks) {
    Write-Host "Git zainstalowany poprawnie: $(git --version)" -ForegroundColor Green
} else {
    Write-Warning "Instalacja się zakończyła, ale 'git' wciąż nie odpowiada w tej sesji. Zamknij to okno PowerShell, otwórz nowe i sprawdź 'git --version' jeszcze raz — PATH odświeża się dopiero w nowej sesji."
}
