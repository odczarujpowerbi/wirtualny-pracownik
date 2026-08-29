@echo off
REM ============================================================================
REM Start bota "Marketing" (decyzja wlasciciela 29.08.2026) - OSOBNY proces od
REM start-agent-dev.bat (rola "dev") i start-agent-checker.bat (rola "checker"),
REM na TEJ SAMEJ maszynie i repo. Odpala TE SAME job_scheduler.py, ale pod
REM rola "marketing" (BOT_ROLE=marketing) - konto "AI - Marketing" w Projectly,
REM wlasny plik blokady/stanu/historii, i TYLKO joby oznaczone w
REM config/schedule.yaml jako `role: marketing` (dzis: runner_loop_marketing).
REM
REM Wczesniej zadania "AI - Marketing" byly odbierane przy okazji przez proces
REM dev (poll.extra_accounts) - od tej daty to konto zostalo stamtad usuniete,
REM marketing ma wlasny, niezalezny proces (zeby oba nie probowaly przetworzyc
REM tego samego zadania naraz).
REM
REM Uruchamiaj OBOK start-agent-dev.bat, start-agent-checker.bat i
REM start-agent-zarzad.bat (cztery osobne okna/procesy), nie zamiast nich.
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
set BOT_ROLE=marketing
python job_scheduler.py --tick 2
