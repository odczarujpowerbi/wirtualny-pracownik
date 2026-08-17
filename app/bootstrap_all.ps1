# Orkiestrator całego bootstrapu — jedno polecenie zamiast ręcznego
# uruchamiania każdego bootstrap_install_*.ps1 z osobna. Pokazuje na bieżąco
# NUMER KROKU, CO SIĘ DZIEJE i CZAS TRWANIA każdego kroku, a na końcu
# podsumowanie — dokładnie to, o co poprosiłeś ("pełny przebieg oraz
# informacja co robią skrypty" + "czas trwania").
#
# Można uruchomić na dwa sposoby:
#   1. Standalone, na zupełnie świeżej maszynie (bez repo) — sam pobiera
#      brakujące skrypty z GitHuba w razie potrzeby.
#   2. Z folderu app/ w już sklonowanym repo — używa lokalnych plików,
#      nic dodatkowo nie pobiera.
#
# Kroki wymagane (Required=$true) zatrzymują cały przebieg przy błędzie —
# nie ma sensu jechać dalej bez gita/Pythona/repo. Kroki opcjonalne
# (Claude Code) tylko ostrzegają i lecą dalej. Claude Desktop CELOWO nie
# jest tu wpięty — to instalator GUI wymagający klikania, kłóciłby się z
# automatycznym, bezobsługowym przebiegiem; uruchom go osobno po fakcie.
#
# Zapisuje historię przebiegu do runs/bootstrap_history.json — czyta ją
# machine_status_reporter.py, żeby wiedzieć, kiedy i jak poszedł ostatni
# bootstrap tej maszyny.
#
# TESTOWANE w tej sesji pod PowerShell Core: pełny przebieg (wszystkie
# kroki OK, bo maszyna testowa już ma git/Python/Claude Code), oraz
# wymuszona awaria kroku wymaganego (poprawnie przerywa) i opcjonalnego
# (poprawnie ostrzega i leci dalej).
#
# Użycie (najprościej — repo domyślne z parametru $RepoUrl):
#   .\bootstrap_all.ps1
# albo wskazując inne repo/fork:
#   .\bootstrap_all.ps1 -RepoUrl "https://github.com/<org>/<repo>.git"

param(
    # Repozytorium projektu — jedno miejsce do zmiany przy forku/innym repo.
    # Trzymaj zgodne z config/repo.yaml (ten skrypt działa PRZED klonem, więc
    # nie może wczytać tamtego pliku). Baza raw niżej wylicza się z tej wartości.
    [string]$RepoUrl = "https://github.com/odczarujpowerbi/wirtualny-pracownik.git",

    [string]$InstallPath = "C:\AIWorker",

    [string]$Branch = "main",

    [switch]$SkipClaudeCode
)

$ErrorActionPreference = "Stop"
# Baza raw.githubusercontent wyliczana z $RepoUrl + $Branch — dzięki temu jedyna
# wartość do zmiany przy forku to $RepoUrl. Kod leży w korzeniu repo, więc app/.
$repoSlug = ($RepoUrl -replace '^https://github\.com/', '') -replace '\.git$', ''
$RAW_BASE = "https://raw.githubusercontent.com/$repoSlug/$Branch/app"

function Get-BootstrapScriptPath($name) {
    $localCandidate = Join-Path $PSScriptRoot $name
    if (Test-Path $localCandidate) {
        return $localCandidate
    }
    # Zawsze pobieramy ŚWIEŻĄ kopię do Temp (nadpisując starszą). Wcześniej
    # skrypt REUŻYWAŁ starej kopii z Temp, jeśli tam była — po zmianie repo/gałęzi
    # znaczyło to, że stara wersja (np. z gałęzią new-repo-i29t2e) była po cichu
    # uruchamiana ponownie mimo poprawek w repo. Realny błąd napotkany na VM.
    $tempPath = Join-Path $env:TEMP $name
    Invoke-RestMethod -Uri "$RAW_BASE/$name" -OutFile $tempPath
    return $tempPath
}

function Invoke-PowerShellScript($scriptPath, $scriptArgs) {
    # WAŻNE: uruchamiane jako OSOBNY PROCES (nie `& $scriptPath` w tym samym
    # procesie), bo sub-skrypty kończą się przez `exit` przy błędzie — `exit`
    # wywołany w tym samym procesie zamknąłby CAŁY orkiestrator, nie tylko
    # ten krok. $PID-owy plik wykonywalny = ten sam shell, w którym już jesteś
    # (powershell.exe albo pwsh), więc nie przełącza Cię niespodziewanie na inny.
    # WAŻNE: `| Out-Host` na końcu jest konieczne — bez tego wyjście konsoli
    # podprocesu (Write-Host z gita/Pythona/Claude Code) wpada do STRUMIENIA
    # ZWRACANEGO przez tę funkcję razem z $LASTEXITCODE, psując dalsze
    # sprawdzanie kodu wyjścia (realnie napotkane i naprawione w tej sesji —
    # `$exitCode -eq 0` na zanieczyszczonej tablicy dawało błędny wynik).
    # Out-Host nadal POKAZUJE tekst na żywo, tylko nie dodaje go do wyniku.
    $psExe = (Get-Process -Id $PID).Path
    & $psExe -NoProfile -ExecutionPolicy Bypass -File $scriptPath @scriptArgs | Out-Host
    return $LASTEXITCODE
}

function Invoke-PythonScript($workDir, $scriptName) {
    Push-Location $workDir
    try {
        python $scriptName | Out-Host
        return $LASTEXITCODE
    } finally {
        Pop-Location
    }
}

$appPath = Join-Path $InstallPath "wirtualny-pracownik\app"

$steps = @(
    @{ Name = "Git"; Required = $true; Run = { Invoke-PowerShellScript (Get-BootstrapScriptPath "bootstrap_install_git.ps1") @() } }
    @{ Name = "Python 3.11+"; Required = $true; Run = { Invoke-PowerShellScript (Get-BootstrapScriptPath "bootstrap_install_python.ps1") @() } }
    @{ Name = "Claude Code (CLI)"; Required = $false; Run = { Invoke-PowerShellScript (Get-BootstrapScriptPath "bootstrap_install_claude_code.ps1") @() } }
    @{ Name = "Pobranie repo + zależności Pythona"; Required = $true; Run = { Invoke-PowerShellScript (Get-BootstrapScriptPath "bootstrap_install.ps1") @("-RepoUrl", $RepoUrl, "-InstallPath", $InstallPath, "-Branch", $Branch, "-SkipSystemChecks") } }
    @{ Name = "Inicjalizacja sekretów (secrets/)"; Required = $true; Run = { Invoke-PythonScript $appPath "bootstrap_init_secrets.py" } }
    @{ Name = "Test dymny"; Required = $true; Run = { Invoke-PythonScript $appPath "bootstrap_smoke_test.py" } }
)

if ($SkipClaudeCode) {
    $steps = $steps | Where-Object { $_.Name -ne "Claude Code (CLI)" }
}

$total = $steps.Count
$results = @()
$stoppedEarly = $false

Write-Host "=== Bootstrap Wirtualnego Pracownika — $total kroków ===" -ForegroundColor Cyan

for ($i = 0; $i -lt $total; $i++) {
    $step = $steps[$i]
    $num = $i + 1

    Write-Host "`n[$num/$total] $($step.Name)..." -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()

    $exitCode = 1
    $errorMessage = $null
    try {
        $exitCode = & $step.Run
    } catch {
        $errorMessage = $_.Exception.Message
    }
    $sw.Stop()
    $elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)

    $ok = ($exitCode -eq 0) -and (-not $errorMessage)
    $status = if ($ok) { "OK" } else { "BLAD" }
    $color = if ($ok) { "Green" } else { if ($step.Required) { "Red" } else { "Yellow" } }

    Write-Host "[$num/$total] $($step.Name) -> $status (${elapsed}s)" -ForegroundColor $color
    if (-not $ok -and $errorMessage) {
        Write-Host "        Błąd: $errorMessage" -ForegroundColor $color
    }

    $results += [PSCustomObject]@{
        step = $step.Name
        required = $step.Required
        status = $status
        elapsed_seconds = $elapsed
        finished_at = (Get-Date).ToString("o")
    }

    if (-not $ok -and $step.Required) {
        Write-Host "`nKrok wymagany zakończony błędem — przerywam dalszy bootstrap." -ForegroundColor Red
        $stoppedEarly = $true
        break
    }
}

Write-Host "`n=== Podsumowanie ===" -ForegroundColor Cyan
# Ręczne formatowanie zamiast Format-Table -AutoSize: to drugie potrafi nie
# wypisać nic, gdy nie ma prawdziwej konsoli (np. log z Harmonogramu zadań
# przekierowany do pliku) — realnie napotkane i naprawione w tej sesji.
foreach ($r in $results) {
    $marker = if ($r.status -eq "OK") { "[OK]  " } else { "[BLAD]" }
    Write-Host ("{0} {1,-45} {2,6}s" -f $marker, $r.step, $r.elapsed_seconds)
}

$totalElapsed = [math]::Round(($results | Measure-Object -Property elapsed_seconds -Sum).Sum, 1)
Write-Host "Łączny czas: ${totalElapsed}s"

$historyDir = Join-Path $appPath "runs"
if (Test-Path $appPath) {
    New-Item -ItemType Directory -Path $historyDir -Force | Out-Null
    $historyPath = Join-Path $historyDir "bootstrap_history.json"
    @{
        run_at = (Get-Date).ToString("o")
        stopped_early = $stoppedEarly
        steps = $results
    } | ConvertTo-Json -Depth 5 | Set-Content -Path $historyPath -Encoding UTF8
    Write-Host "`nHistoria zapisana: $historyPath (czyta ją machine_status_reporter.py)"
}

if ($stoppedEarly) {
    exit 1
}

Write-Host "`nGotowe. Następne kroki:" -ForegroundColor Green
Write-Host "  1. Uzupełnij secrets\.env i secrets\mcp\*.json"
Write-Host "  2. python bootstrap_register.py <rola>"
Write-Host "  3. Zarejestruj JEDNO zadanie w Harmonogramie zadań: python job_scheduler.py (Rozpocznij w: $appPath)"
Write-Host "  4. python job_scheduler.py --status   # podgląd stanu wszystkich zadań cyklicznych"
