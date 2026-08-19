# Przygotowanie srodowiska na nowej maszynie - JEDEN program spinajacy wszystkie
# kroki instalacji i konfiguracji. Uruchamiany dwuklikiem przez
# "Przygotuj-srodowisko.bat" (obok tego pliku).
#
# Kolejnosc krokow:
#   1. Git                 (wymagane)
#   2. Python 3.11+        (wymagane)
#   3. Claude Code (CLI)   - naped glownego modelu agenta
#   4. VS Code + rozszerzenie Claude Code - kodowanie z agentem w edytorze
#   5. Microsoft Office / 365 Apps - Excel/Word dla MCP i botow czytajacych ekran (kilka GB)
#   6. Aplikacje (Power BI, Obsidian, Teams, Outlook, Chrome, Terminal)
#   7. Modele lokalne (Ollama) - tania druga opinia / computer use (kilka GB)
#   8. OneDrive            - lokalny sync projektow stron i skilli
#   9. Zaleznosci Pythona  - pip install -r requirements.txt (jesli repo obok)
#  10. Sekrety + rejestracja roli + test dymny (finalizacja aplikacji)
#  11. Logowania           - interaktywny checklist kont (chmura, personalne, Meta, Gmail...)
#  12. Raport stanu        - zdjecie konfiguracji do instalacja/STAN-SRODOWISKA.txt
#
# Przelaczniki:
#   -SkipOffice       pomija Office
#   -SkipApps         pomija dodatkowe aplikacje (Power BI, Obsidian, Teams, ...)
#   -SkipLocalModel   pomija modele lokalne (kilka GB)
#   -SkipLogins       pomija interaktywny checklist logowan
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
param(
    [switch]$SkipOffice,
    [switch]$SkipApps,
    [switch]$SkipLocalModel,
    [switch]$SkipLogins
)

$ErrorActionPreference = "Stop"
$appDir = Resolve-Path (Join-Path $PSScriptRoot "..\app")

function Invoke-Step($scriptName, $stepArgs) {
    $path = Join-Path $appDir $scriptName
    if (-not (Test-Path $path)) { throw "Brak skryptu: $path" }
    $psExe = (Get-Process -Id $PID).Path
    & $psExe -NoProfile -ExecutionPolicy Bypass -File $path @stepArgs | Out-Host
    return $LASTEXITCODE
}

function Invoke-Python($scriptOrArgs) {
    Push-Location $appDir
    try { & python @scriptOrArgs | Out-Host; return $LASTEXITCODE }
    finally { Pop-Location }
}

$steps = @(
    @{ Name = "Git";                              Required = $true;  Run = { Invoke-Step "bootstrap_install_git.ps1" @() } }
    @{ Name = "Python 3.11+";                     Required = $true;  Run = { Invoke-Step "bootstrap_install_python.ps1" @() } }
    @{ Name = "Claude Code (CLI)";                Required = $false; Run = { Invoke-Step "bootstrap_install_claude_code.ps1" @() } }
    @{ Name = "VS Code + rozszerzenie";           Required = $false; Run = { Invoke-Step "bootstrap_install_vscode.ps1" @() } }
)
if (-not $SkipOffice) {
    $steps += @{ Name = "Microsoft Office / 365 Apps"; Required = $false; Run = { Invoke-Step "bootstrap_install_office.ps1" @() } }
}
if (-not $SkipApps) {
    $steps += @{ Name = "Aplikacje (Power BI, Obsidian, Teams...)"; Required = $false; Run = { Invoke-Step "bootstrap_install_apps.ps1" @() } }
}
if (-not $SkipLocalModel) {
    $steps += @{ Name = "Modele lokalne (Ollama)"; Required = $false; Run = { Invoke-Step "bootstrap_install_local_model.ps1" @() } }
}
$steps += @{ Name = "OneDrive (sync)";            Required = $false; Run = { Invoke-Step "bootstrap_setup_onedrive.ps1" @() } }
$steps += @{ Name = "Zaleznosci Pythona";         Required = $false; Run = {
    if (Test-Path (Join-Path $appDir "requirements.txt")) { Invoke-Python @("-m", "pip", "install", "-r", "requirements.txt") } else { 0 }
} }
# Finalizacja aplikacji - zeby jeden przebieg dawal GOTOWE narzedzie, nie samo
# srodowisko. Idempotentne: init_secrets nigdy nie nadpisuje wypelnionych plikow,
# register zapisuje role, smoke test tylko weryfikuje.
$steps += @{ Name = "Sekrety (secrets/)";         Required = $false; Run = { Invoke-Python @("bootstrap_init_secrets.py") } }
$steps += @{ Name = "Rejestracja roli (dev)";     Required = $false; Run = { Invoke-Python @("bootstrap_register.py", "dev") } }
if (-not $SkipLogins) {
    $steps += @{ Name = "Logowania (checklist)";  Required = $false; Run = { Invoke-Step "bootstrap_logins.ps1" @() } }
}
$steps += @{ Name = "Test dymny";                 Required = $false; Run = { Invoke-Python @("bootstrap_smoke_test.py") } }
$steps += @{ Name = "Raport stanu srodowiska";    Required = $false; Run = { Invoke-Step "bootstrap_env_report.ps1" @() } }

$total = $steps.Count
$results = @()
Write-Host "=== Przygotowanie srodowiska - $total krokow ===" -ForegroundColor Cyan

for ($i = 0; $i -lt $total; $i++) {
    $step = $steps[$i]; $num = $i + 1
    Write-Host "`n[$num/$total] $($step.Name)..." -ForegroundColor Cyan
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $exitCode = 1; $errorMessage = $null
    try { $exitCode = & $step.Run } catch { $errorMessage = $_.Exception.Message }
    $sw.Stop()
    $elapsed = [math]::Round($sw.Elapsed.TotalSeconds, 1)
    $ok = ($exitCode -eq 0) -and (-not $errorMessage)
    $color = if ($ok) { "Green" } else { if ($step.Required) { "Red" } else { "Yellow" } }
    Write-Host "[$num/$total] $($step.Name) -> $(if ($ok) {'OK'} else {'BLAD'}) (${elapsed}s)" -ForegroundColor $color
    if (-not $ok -and $errorMessage) { Write-Host "        Blad: $errorMessage" -ForegroundColor $color }
    $results += [PSCustomObject]@{ step = $step.Name; ok = $ok; required = $step.Required; elapsed = $elapsed }
    if (-not $ok -and $step.Required) {
        Write-Host "`nKrok wymagany zakonczony bledem - przerywam." -ForegroundColor Red
        break
    }
}

Write-Host "`n=== Podsumowanie ===" -ForegroundColor Cyan
foreach ($r in $results) {
    $marker = if ($r.ok) { "[OK]  " } else { "[BLAD]" }
    Write-Host ("{0} {1,-35} {2,6}s" -f $marker, $r.step, $r.elapsed)
}
Write-Host "`nGotowe. Podglad: python app\dashboard.py -> http://127.0.0.1:8787/"
exit 0
