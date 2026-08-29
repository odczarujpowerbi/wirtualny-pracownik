@echo off
REM ============================================================================
REM Start bota "Dev" (BOT_ROLE=dev, konto "AI - Dev" w Projectly) - jeden z
REM czterech niezaleznych procesow (dev/checker/marketing/zarzad), kazdy w
REM osobnym oknie/procesie (patrz start-agent-checker.bat/start-agent-marketing.bat/
REM start-agent-zarzad.bat i start-agent-all.bat, ktory odpala wszystkie naraz).
REM Przemianowany z "start-agent.bat" 29.08.2026 (spojnosc nazw z pozostalymi
REM trzema) - jesli masz stare zadanie w Harmonogramie Windows wskazujace na
REM stara nazwe, przerejestruj przez register-task-dev.ps1.
REM
REM Uruchamia centralny scheduler (job_scheduler.py), ktory wg config/schedule.yaml
REM odpala runner_loop + monitoring zdrowia + samo-weryfikacje.
REM
REM --tick 2: decyzja wlasciciela 22.08.2026 - zadania w Projectly maja byc
REM podchwytywane od razu, nie po do 30s (harmonogram sprawdza teraz co 2s;
REM interwal per-zadanie w schedule.yaml, np. runner_loop, tez ustawiony na 2s).
REM
REM Rejestrowany w Harmonogramie zadan Windows przez register-task-dev.ps1
REM (wyzwalacz: przy zalogowaniu uzytkownika). Podglad na zywo: start-dashboard.bat
REM (albo python app\dashboard.py) -> http://127.0.0.1:8787/
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
python job_scheduler.py --tick 2
