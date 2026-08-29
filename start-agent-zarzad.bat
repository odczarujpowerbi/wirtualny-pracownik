@echo off
REM ============================================================================
REM Start bota "Zarzad" (decyzja wlasciciela 29.08.2026) - OSOBNY proces od
REM start-agent-dev.bat (rola "dev"), start-agent-checker.bat (rola "checker")
REM i start-agent-marketing.bat (rola "marketing"), na TEJ SAMEJ maszynie i
REM repo. Odpala TE SAME job_scheduler.py, ale pod rola "zarzad" (BOT_ROLE=zarzad)
REM - konto "AI - Zarzad" w Projectly, wlasny plik blokady/stanu/historii, i
REM TYLKO joby oznaczone w config/schedule.yaml jako `role: zarzad` (dzis:
REM runner_loop_zarzad, escalation_watcher_zarzad).
REM
REM Wczesniej zadania konta "AI - Zarzad" byly odbierane przy okazji przez
REM proces "dev" (poll.extra_accounts w config/projectly.yaml) - od tej daty
REM ten wpis usuniety, zarzad ma wlasny, niezalezny proces.
REM
REM Uruchamiaj OBOK pozostalych trzech (cztery osobne okna/procesy), nie
REM zamiast nich.
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
set BOT_ROLE=zarzad
python job_scheduler.py --tick 2
