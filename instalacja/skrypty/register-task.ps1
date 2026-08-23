# ============================================================================
# Rejestruje autonomiczny start Wirtualnego Pracownika w Harmonogramie zadan
# Windows. Wyzwalacz: przy zalogowaniu uzytkownika (NIE wymaga uprawnien
# administratora, w odroznieniu od "przy starcie systemu"). Idempotentne:
# -Force nadpisuje istniejace zadanie.
#
# Uruchomienie:  powershell -ExecutionPolicy Bypass -File register-task.ps1
# Usuniecie:     Unregister-ScheduledTask -TaskName "WirtualnyPracownikAI" -Confirm:$false
#
# Plik celowo w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM.
# ============================================================================
$ErrorActionPreference = "Stop"
$taskName = "WirtualnyPracownikAI"
# start-agent.bat mieszka w KORZENIU repo, nie w tym folderze (instalacja/skrypty/)
# - dwa poziomy wyzej. Zla wersja tej linii (Join-Path $PSScriptRoot "start-agent.bat")
# nigdy nie trafiala na plik, ale nikt tego nie zauwazyl, bo zadanie bylo juz
# zarejestrowane recznie/inaczej (naprawione 23.08.2026).
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$batPath = Join-Path $repoRoot "start-agent.bat"

if (-not (Test-Path $batPath)) { throw "Brak pliku startowego: $batPath" }

$action   = New-ScheduledTaskAction -Execute $batPath
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Autonomiczny scheduler agentow: runner_loop co 30s + monitoring + samo-weryfikacja." | Out-Null

Write-Host "Zarejestrowano zadanie '$taskName' (start przy zalogowaniu uzytkownika)."
Write-Host "Podglad na zywo: python app\dashboard.py  ->  http://127.0.0.1:8787/"
