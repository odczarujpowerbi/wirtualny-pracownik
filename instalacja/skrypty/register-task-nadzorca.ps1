# ============================================================================
# Rejestruje NADZORCE w Harmonogramie zadan Windows - jedyny proces, ktory ma
# domyslnie startowac przy zalogowaniu (decyzja wlasciciela 01.09.2026).
# Boty (dev/checker/marketing/zarzad) odpala juz sam nadzorca, na podstawie
# statusu zadania sterujacego w Projectly - dlatego ten skrypt PRZY OKAZJI
# wylacza stare zadania logowania, ktore startowaly boty bezposrednio.
#
# Wyzwalacz: przy zalogowaniu uzytkownika (NIE wymaga uprawnien administratora,
# w odroznieniu od "przy starcie systemu"). Idempotentne: -Force nadpisuje.
#
# Uruchomienie:  powershell -ExecutionPolicy Bypass -File register-task-nadzorca.ps1
# Usuniecie:     Unregister-ScheduledTask -TaskName "WirtualnyPracownikAI-Nadzorca" -Confirm:$false
#
# Plik celowo w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM.
# ============================================================================
$ErrorActionPreference = "Stop"
$taskName = "WirtualnyPracownikAI-Nadzorca"

# start-nadzorca.bat mieszka w KORZENIU repo, nie w tym folderze
# (instalacja/skrypty/) - dwa poziomy wyzej.
$repoRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$batPath = Join-Path $repoRoot "start-nadzorca.bat"

if (-not (Test-Path $batPath)) { throw "Brak pliku startowego: $batPath" }

$action   = New-ScheduledTaskAction -Execute $batPath
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description "Nadzorca: czyta status zadan sterujacych w Projectly i odpala tylko te boty, ktore maja byc wlaczone." | Out-Null

Write-Host "Zarejestrowano zadanie '$taskName' (start przy zalogowaniu uzytkownika)."

# Stare zadania startujace boty BEZPOSREDNIO - od teraz robi to nadzorca, wiec
# zostaja wylaczone (nie usuwane: gdyby trzeba bylo wrocic do starego ukladu,
# wystarczy Enable-ScheduledTask). "WirtualnyPracownikAI" dodatkowo wskazywalo
# na nieistniejacy start-agent.bat (przemianowany na start-agent-dev.bat
# 29.08.2026) i od tamtej pory konczylo sie bledem przy kazdym logowaniu.
$stareZadania = @(
    "WirtualnyPracownikAI",              # rola dev (register-task-dev.ps1)
    "WirtualnyPracownikAI-Checker",
    "WirtualnyPracownikAI-Marketing",
    "WirtualnyPracownikAI-Zarzad"
)
foreach ($stare in $stareZadania) {
    $zadanie = Get-ScheduledTask -TaskName $stare -ErrorAction SilentlyContinue
    if ($null -ne $zadanie) {
        Disable-ScheduledTask -TaskName $stare | Out-Null
        Write-Host "Wylaczono stare zadanie '$stare' (boty odpala teraz nadzorca)."
    }
}

Write-Host ""
Write-Host "Stan zadan sterujacych bez czekania na petle:  python app\agent_supervisor.py --status"
Write-Host "Panel operatora:  start-dashboard.bat  ->  http://127.0.0.1:8787/"
