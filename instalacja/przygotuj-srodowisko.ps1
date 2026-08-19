# Przygotowanie srodowiska na nowej maszynie - JEDEN program spinajacy wszystkie
# kroki instalacji i konfiguracji. Uruchamiany dwuklikiem przez
# "Przygotuj-srodowisko.bat" (obok tego pliku).
#
# Kolejnosc krokow:
#   1. Git                 (wymagane)
#   2. Python 3.11+        (wymagane)
#   3. Claude Code (CLI)   - naped glownego modelu agenta
#   4. VS Code + rozszerzenie Claude Code - kodowanie z agentem w edytorze
#   5. Modele lokalne (Ollama) - tania druga opinia / computer use (kilka GB)
#   6. OneDrive            - lokalny sync projektow stron i skilli
#   7. Zaleznosci Pythona  - pip install -r requirements.txt (jesli repo obok)
#   8. Logowania           - interaktywny checklist kont (chmura, personalne, Meta, Gmail...)
#   9. Raport stanu        - zdjecie konfiguracji do instalacja/STAN-SRODOWISKA.txt
#
# Przelaczniki:
#   -SkipLocalModel   pomija krok 5 (gdy nie chcesz pobierac kilku GB)
#   -SkipLogins       pomija krok 8 (interaktywny)
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
param(
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
if (-not $SkipLocalModel) {
    $steps += @{ Name = "Modele lokalne (Ollama)"; Required = $false; Run = { Invoke-Step "bootstrap_install_local_model.ps1" @() } }
}
$steps += @{ Name = "OneDrive (sync)";            Required = $false; Run = { Invoke-Step "bootstrap_setup_onedrive.ps1" @() } }
$steps += @{ Name = "Zaleznosci Pythona";         Required = $false; Run = {
    if (Test-Path (Join-Path $appDir "requirements.txt")) { Invoke-Python @("-m", "pip", "install", "-r", "requirements.txt") } else { 0 }
} }
if (-not $SkipLogins) {
    $steps += @{ Name = "Logowania (checklist)";  Required = $false; Run = { Invoke-Step "bootstrap_logins.ps1" @() } }
}
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
