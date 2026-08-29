@echo off
REM ============================================================================
REM Start bota "Checker" (decyzja wlasciciela 29.08.2026) - OSOBNY proces od
REM start-agent.bat (rola "dev"), na TEJ SAMEJ maszynie i repo. Odpala TE SAME
REM job_scheduler.py, ale pod rola "checker" (BOT_ROLE=checker) - konto
REM "AI-Checker" w Projectly, wlasny plik blokady/stanu/historii (patrz
REM scheduler_lock.py, job_scheduler.py _status_path_for_role), i TYLKO joby
REM oznaczone w config/schedule.yaml jako `role: checker`:
REM   - repo_auto_improver  - jedyny bot z dostepem do repozytorium (Read/Write/
REM     Edit w izolowanym git worktree, commit/PR robi kod Pythona, nie model)
REM   - runner_loop_checker - wlasne, drobne zadania operacyjne przypisane
REM     do konta "AI-Checker" (nie tylko naprawa repo)
REM
REM Ta zdolnosc (edycja/nadpisanie repo) jest CELOWO niedostepna z roli dev/
REM marketing - stad osobne konto i osobny proces, nie flaga w tym samym bocie.
REM
REM Uruchamiaj OBOK start-agent.bat (dwa osobne okna/procesy), nie zamiast niego.
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
set BOT_ROLE=checker
python job_scheduler.py --tick 2
