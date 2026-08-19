# Rejestruje job_scheduler.py jako zadanie w Harmonogramie zadań Windows —
# uruchamiane automatycznie przy logowaniu, żeby runner chodził 24/7 bez
# ręcznego startu. Zastępuje ręczne klikanie w Harmonogramie ("krok na stałe"
# z INSTRUKCJA-WDROZENIA.md). job_scheduler.py to długo działająca pętla, więc
# wystarczy jeden wyzwalacz przy logowaniu — proces zostaje żywy.
#
# Uruchom RAZ, po smoke teście, jako Administrator:
#   .\bootstrap_register_task.ps1
#
# Domyślnie: bieżący użytkownik, przy logowaniu, najwyższe uprawnienia, start od
# razu, restart przy awarii, bez limitu czasu. Zakłada dedykowane konto bota z
# autologowaniem (dokumentacja bazowa: komputer 24/7). Idempotentne (-Force).

param(
    [string]$AppPath = "C:\AIWorker\wirtualny-pracownik\app",
    [string]$TaskName = "WirtualnyPracownik"
)

$ErrorActionPreference = "Stop"

# 1. Znajdź Pythona (pełna ścieżka do exe — Harmonogram nie zna aliasów PATH).
$python = (Get-Command python -ErrorAction SilentlyContinue).Path
if (-not $python) {
    Write-Error "Nie znaleziono 'python' w PATH. Zainstaluj Pythona (bootstrap_install_python.ps1) i spróbuj ponownie."
    exit 1
}

# 2. Sprawdź, że job_scheduler.py istnieje pod podaną ścieżką.
$script = Join-Path $AppPath "job_scheduler.py"
if (-not (Test-Path $script)) {
    Write-Error "Nie znaleziono $script. Podaj poprawny -AppPath (domyślnie C:\AIWorker\wirtualny-pracownik\app)."
    exit 1
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

Write-Host "Rejestruję zadanie '$TaskName':" -ForegroundColor Cyan
Write-Host "  Program:      $python"
Write-Host "  Argument:     job_scheduler.py"
Write-Host "  Rozpocznij w: $AppPath"
Write-Host "  Uzytkownik:   $currentUser (przy logowaniu)"

# 3. Akcja, wyzwalacz (przy logowaniu bota), ustawienia dla procesu 24/7.
$action = New-ScheduledTaskAction -Execute $python -Argument "job_scheduler.py" -WorkingDirectory $AppPath
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $currentUser -LogonType Interactive -RunLevel Highest

# 4. Rejestracja (nadpisuje istniejące zadanie o tej nazwie).
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Write-Host "`nZadanie zarejestrowane." -ForegroundColor Green

# 5. Uruchom od razu (bez czekania na kolejne logowanie).
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
$info = Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo
Write-Host "Stan: $((Get-ScheduledTask -TaskName $TaskName).State) | ostatni wynik: $($info.LastTaskResult)"

Write-Host "`nPrzydatne polecenia:" -ForegroundColor Cyan
Write-Host "  Podglad stanu:  Get-ScheduledTask -TaskName '$TaskName' | Get-ScheduledTaskInfo"
Write-Host "  Zatrzymaj:      Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Usun:           Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host "  Status runnera: python job_scheduler.py --status"
