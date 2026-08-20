@echo off
REM ============================================================================
REM  LOGOWANIA - osobny, szybki krok PO instalacji (dwuklik).
REM  Instalacja srodowiska jest bezobslugowa; tu logujesz sie na konta, gdy
REM  wszystko jest juz zainstalowane. Skrypt prowadzi krok po kroku i otwiera
REM  odpowiednie aplikacje/strony (Claude, VS Code chmura+personalne, Microsoft
REM  365, Office aktywacja, Gmail, Meta Business, GitHub).
REM ============================================================================
chcp 65001 > nul
echo.
echo === Logowania na konta - Wirtualny Pracownik AI ===
echo Przejdziemy po kolei. Dla kazdego konta otworze aplikacje/strone i zapytam,
echo czy zalogowane.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0skrypty\bootstrap_logins.ps1"
echo.
echo === Provisioning zasobow Claude (skille / agenci / pluginy) ===
echo Teraz, gdy OneDrive i Claude sa zalogowane, dogram Twoj zestaw skilli i pluginow do ~/.claude.
echo (Mozesz pominac zamykajac to okno - uruchomisz pozniej: skrypty\bootstrap_install_claude_assets.ps1)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0skrypty\bootstrap_install_claude_assets.ps1"
echo.
pause
