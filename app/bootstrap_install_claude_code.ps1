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

function Test-ClaudeCodeWorks {
    try {
        $output = & claude --version 2>&1
        return ($LASTEXITCODE -eq 0) -and ($output -match "Claude Code")
    } catch {
        return $false
    }
}

if (Test-ClaudeCodeWorks) {
    Write-Host "Claude Code już jest zainstalowany: $(claude --version)" -ForegroundColor Green
    exit 0
}

Write-Host "Instaluję Claude Code (natywny instalator)..." -ForegroundColor Cyan
irm https://claude.ai/install.ps1 | iex

# Odśwież PATH w BIEŻĄCEJ sesji PowerShell, żeby nie trzeba było jej zamykać.
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")

if (Test-ClaudeCodeWorks) {
    Write-Host "Claude Code zainstalowany poprawnie: $(claude --version)" -ForegroundColor Green
    Write-Host "Następny krok: uruchom 'claude' i zaloguj się (albo ustaw ANTHROPIC_API_KEY w secrets\.env)."
} else {
    Write-Warning "Instalacja się zakończyła, ale 'claude' wciąż nie odpowiada w tej sesji. Zamknij to okno PowerShell, otwórz nowe i sprawdź 'claude --version' jeszcze raz."
}
