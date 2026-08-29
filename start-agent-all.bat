@echo off
REM ============================================================================
REM Uruchamia WSZYSTKICH czterech botow naraz, kazdego w OSOBNYM, WIDOCZNYM
REM oknie konsoli (zadanie wlasciciela 29.08.2026: "kazdy wtedy pracuje w
REM swoim osobnym okienku") - inny mechanizm niz przycisk "Uruchom wszystkich"
REM w dashboardzie (ktory celowo odpala procesy NIEWIDOCZNIE, bez okna, patrz
REM dashboard.py _launch_process/CREATE_NO_WINDOW). To jest wersja do klikania
REM w Eksploratorze/na pulpicie, gdzie chcesz WIDZIEC logi kazdego bota na biezaco.
REM
REM Zamkniecie tego okna NIE zamyka czterech odpalonych - kazde jest w swoim
REM wlasnym, niezaleznym oknie cmd (start "..." cmd /k ...).
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0"
start "Wirtualny Pracownik - Dev"       cmd /k start-agent-dev.bat
start "Wirtualny Pracownik - Checker"   cmd /k start-agent-checker.bat
start "Wirtualny Pracownik - Marketing" cmd /k start-agent-marketing.bat
start "Wirtualny Pracownik - Zarzad"    cmd /k start-agent-zarzad.bat
