# Autostart 24/7: uruchamia job_scheduler.py (petla agenta) automatycznie przy
# zalogowaniu. Dwie drogi, z fallbackiem:
#   1. Harmonogram zadan Windows (preferowane) - restart przy awarii, bez limitu czasu.
#   2. Folder Startup (gdy Harmonogram odmawia - realnie napotkane "Odmowa dostepu"
#      bez admina) - prostszy skrot uruchamiany przy logowaniu.
# Idempotentne: nadpisuje istniejace zadanie / skrot.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_autostart.ps1 [-AppPath ...]
param(
    [string]$AppPath = $PSScriptRoot,   # domyslnie folder app/ (ten, w ktorym lezy ten skrypt)
    [string]$TaskName = "WirtualnyPracownikAI"
)
$ErrorActionPreference = "Stop"

$python = (Get-Command python -ErrorAction SilentlyContinue).Path
if (-not $python) { Write-Host "UWAGA: brak 'python' w PATH - pomijam autostart."; exit 1 }

$script = Join-Path $AppPath "job_scheduler.py"
if (-not (Test-Path $script)) { Write-Host "UWAGA: brak $script - pomijam autostart."; exit 1 }

Write-Host "=== Autostart 24/7 (job_scheduler.py) ==="
Write-Host "  Python:       $python"
Write-Host "  Katalog app:  $AppPath"

# --- Droga 1: Harmonogram zadan ---
$scheduled = $false
try {
    $user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $action = New-ScheduledTaskAction -Execute $python -Argument "job_scheduler.py" -WorkingDirectory $AppPath
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force | Out-Null
    Write-Host "OK: zarejestrowano w Harmonogramie zadan ('$TaskName', przy logowaniu)." -ForegroundColor Green
    $scheduled = $true
} catch {
    Write-Host "Harmonogram zadan odmowil ($($_.Exception.Message))." -ForegroundColor Yellow
    Write-Host "Przechodze na fallback: folder Startup (bez admina)."
}

# --- Droga 2: folder Startup (fallback) ---
if (-not $scheduled) {
    $startup = [Environment]::GetFolderPath("Startup")
    $launcher = Join-Path $startup "WirtualnyPracownikAI.bat"
    $content = @(
        '@echo off',
        'REM Autostart Wirtualnego Pracownika (folder Startup - bez admina, przy logowaniu).',
        'chcp 65001 > nul',
        "cd /d ""$AppPath""",
        "start ""WirtualnyPracownik"" /min ""$python"" job_scheduler.py"
    ) -join "`r`n"
    Set-Content -Path $launcher -Value $content -Encoding ASCII
    Write-Host "OK: utworzono skrot autostartu w folderze Startup:" -ForegroundColor Green
    Write-Host "  $launcher"
}

Write-Host "Autostart skonfigurowany. Podglad: python dashboard.py -> http://127.0.0.1:8787/"
exit 0
