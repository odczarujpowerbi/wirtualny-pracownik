@echo off
REM ============================================================================
REM Autonomiczny start Wirtualnego Pracownika AI.
REM Uruchamia centralny scheduler (job_scheduler.py), ktory wg config/schedule.yaml
REM odpala runner_loop + monitoring zdrowia + samo-weryfikacje. To JEDYNY
REM proces, ktory trzeba trzymac wlaczony - reszta chodzi z harmonogramu w srodku.
REM
REM --tick 2: decyzja wlasciciela 22.08.2026 - zadania w Projectly maja byc
REM podchwytywane od razu, nie po do 30s (harmonogram sprawdza teraz co 2s;
REM interwal per-zadanie w schedule.yaml, np. runner_loop, tez ustawiony na 2s).
REM
REM Rejestrowany w Harmonogramie zadan Windows przez register-task.ps1
REM (wyzwalacz: przy zalogowaniu uzytkownika). Podglad na zywo: python app\dashboard.py
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
python job_scheduler.py --tick 2
