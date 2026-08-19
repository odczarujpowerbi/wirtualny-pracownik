# Instaluje Claude Code (CLI) — narzędzie terminalowe, którym rozwijany
# jest ten mechanizm. Nie jest wymagane do samego DZIAŁANIA runner_loop.py
# (ten woła pakiet Python 'anthropic' bezpośrednio) — jest za to potrzebne,
# żeby na docelowej maszynie dało się dalej poprawiać/rozbudowywać ten
# kod tak samo, jak było robione w tej sesji.
#
# Oficjalna metoda instalacji (code.claude.com/docs/en/quickstart): natywny
# instalator, jedna komenda, BEZ Node.js/npm — starsza metoda przez
# `npm install -g @anthropic-ai/claude-code` nadal działa, ale to już nie
# jest rekomendowana ścieżka.
#
# TESTOWANE w tej sesji pod PowerShell Core: funkcja wykrywania
# (Test-ClaudeCodeWorks) w obu kierunkach. NIEtestowane: samo pobranie
# instalatora — domena downloads.claude.ai jest zablokowana w sieci TEJ
# sesji budowy (potwierdzone: "gateway answered 403 to CONNECT, policy
# denial"), co jest ograniczeniem środowiska budowy, nie kodu. Prawdziwa
# maszyna z normalnym dostępem do internetu nie napotka tego blokera.
#
# Użycie (PowerShell):
#   .\bootstrap_install_claude_code.ps1

$ErrorActionPreference = "Stop"

# Typowa lokalizacja natywnej instalacji Claude Code, ktora czesto NIE jest w PATH
# (realnie napotkane na VM: "C:\Users\...\.local\bin is not in your PATH"). Bez
# uwzglednienia jej, detekcja zawodzila i skrypt RE-INSTALOWAL Claude Code przy
# kazdym przebiegu (~115s) - dokladnie to "dlugo sie kreci".
$LocalBin = Join-Path $env:USERPROFILE ".local\bin"

function Test-ClaudeCodeWorks {
    # 1) claude w PATH?
    try {
        $output = & claude --version 2>&1
        if (($LASTEXITCODE -eq 0) -and ($output -match "Claude Code")) { return $true }
    } catch { }
    # 2) claude.exe w .local\bin (natywna instalacja poza PATH)? Jesli tak -
    #    dokladamy do PATH biezacej sesji i uznajemy za zainstalowany.
    $exe = Join-Path $LocalBin "claude.exe"
    if (Test-Path $exe) {
        if ($env:Path -notlike "*$LocalBin*") { $env:Path = "$LocalBin;$env:Path" }
        try {
            $output = & $exe --version 2>&1
            if ($output -match "Claude Code") { return $true }
        } catch { }
    }
    return $false
}

function Add-LocalBinToUserPath {
    # KLUCZOWE: natywny instalator klaudka NIE dodaje .local\bin do PATH
    # (komunikat: "is not in your PATH"). Bez tego AGENT (task_thinker) nie
    # znajdzie 'claude' -> brak zywego modelu -> bramka wszystko eskaluje.
    # Dopisujemy .local\bin TRWALE do PATH uzytkownika (nie tylko sesji).
    if (-not (Test-Path (Join-Path $LocalBin "claude.exe"))) { return }
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$LocalBin*") {
        $newPath = if ($userPath) { "$userPath;$LocalBin" } else { $LocalBin }
        [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
        Write-Host "Dodano do PATH uzytkownika (trwale): $LocalBin" -ForegroundColor Green
    }
    if ($env:Path -notlike "*$LocalBin*") { $env:Path = "$LocalBin;$env:Path" }
}

if (Test-ClaudeCodeWorks) {
    Add-LocalBinToUserPath  # nawet gdy juz zainstalowany - upewnij sie, ze jest w PATH
    Write-Host "Claude Code juz jest zainstalowany - pomijam instalacje." -ForegroundColor Green
    exit 0
}

Write-Host "Instaluję Claude Code (natywny instalator)..." -ForegroundColor Cyan
irm https://claude.ai/install.ps1 | iex

# Trwale dodaj .local\bin do PATH uzytkownika + odswiez PATH biezacej sesji.
Add-LocalBinToUserPath
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

if (Test-ClaudeCodeWorks) {
    Write-Host "Claude Code zainstalowany poprawnie: $(claude --version)" -ForegroundColor Green
    Write-Host "Następny krok: uruchom 'claude' i zaloguj się (albo ustaw ANTHROPIC_API_KEY w secrets\.env)."
} else {
    Write-Warning "Instalacja się zakończyła, ale 'claude' wciąż nie odpowiada w tej sesji. Zamknij to okno PowerShell, otwórz nowe i sprawdź 'claude --version' jeszcze raz."
}
