
$ErrorActionPreference = "Stop"
$taskName = "WirtualnyPracownikAI-Checker"
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$batPath = Join-Path $repoRoot "start-agent-checker.bat"

if (-not (Test-Path $batPath)) { throw "Brak pliku startowego: $batPath" }

$action   = New-ScheduledTaskAction -Execute $batPath
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Bot Checker (konto AI-Checker, BOT_ROLE=checker) - jedyny z dostepem do repozytorium (repo_auto_improver.py) i wlasnymi drobnymi zadaniami operacyjnymi. Osobny proces od WirtualnyPracownikAI (dev)." | Out-Null

Write-Host "Zarejestrowano zadanie '$taskName' (start przy zalogowaniu uzytkownika)."
