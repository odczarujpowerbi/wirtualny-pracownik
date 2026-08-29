@echo off
REM ============================================================================
REM Uruchamia panel operatora (app/dashboard.py) - jedno okno w przegladarce,
REM z ktorego widac status wszystkich botow (dev/checker/marketing/zarzad),
REM harmonogram skryptow, historie przebiegow, zuzycie AI i sterowanie
REM (pauza/wznow/stop, uruchom agenta).
REM
REM Serwer sluchaTYLKO na 127.0.0.1:8787 (localhost) - nie jest wystawiony na
REM siec. Zamkniecie tego okna zatrzymuje dashboard, NIE zatrzymuje botow
REM (kazdy dziala jako wlasny, niezalezny proces - patrz start-agent-*.bat).
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
python dashboard.py
