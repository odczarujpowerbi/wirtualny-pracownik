
$ErrorActionPreference = "Stop"
$taskName = "WirtualnyPracownikAI-Marketing"
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$batPath = Join-Path $repoRoot "start-agent-marketing.bat"

if (-not (Test-Path $batPath)) { throw "Brak pliku startowego: $batPath" }

$action   = New-ScheduledTaskAction -Execute $batPath
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Bot Marketing (konto AI - Marketing, BOT_ROLE=marketing) - wlasny, niezalezny proces. Osobny od WirtualnyPracownikAI (dev) i WirtualnyPracownikAI-Checker." | Out-Null

Write-Host "Zarejestrowano zadanie '$taskName' (start przy zalogowaniu uzytkownika)."
