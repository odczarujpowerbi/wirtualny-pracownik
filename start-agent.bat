@echo off
REM ============================================================================
REM Autonomiczny start Wirtualnego Pracownika AI.
REM Uruchamia centralny scheduler (job_scheduler.py), ktory wg config/schedule.yaml
REM odpala runner_loop co 30s + monitoring zdrowia + samo-weryfikacje. To JEDYNY
REM proces, ktory trzeba trzymac wlaczony - reszta chodzi z harmonogramu w srodku.
REM
REM Rejestrowany w Harmonogramie zadan Windows przez register-task.ps1
REM (wyzwalacz: przy zalogowaniu uzytkownika). Podglad na zywo: python app\dashboard.py
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
python job_scheduler.py
