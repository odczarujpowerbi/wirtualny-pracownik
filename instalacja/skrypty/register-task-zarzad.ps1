
$ErrorActionPreference = "Stop"
$taskName = "WirtualnyPracownikAI-Zarzad"
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$batPath = Join-Path $repoRoot "start-agent-zarzad.bat"

if (-not (Test-Path $batPath)) { throw "Brak pliku startowego: $batPath" }

$action   = New-ScheduledTaskAction -Execute $batPath
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Bot Zarzad (konto AI - Zarzad, BOT_ROLE=zarzad) - wlasny, niezalezny proces. Osobny od WirtualnyPracownikAI (dev), WirtualnyPracownikAI-Checker i WirtualnyPracownikAI-Marketing." | Out-Null

Write-Host "Zarejestrowano zadanie '$taskName' (start przy zalogowaniu uzytkownika)."
