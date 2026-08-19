@echo off
REM ============================================================================
REM  JEDEN KLIK: przygotowanie srodowiska Wirtualnego Pracownika na tej maszynie.
REM  Dwuklik w tym pliku uruchamia caly proces instalacji i konfiguracji:
REM  Git, Python, Claude Code, VS Code + rozszerzenie, modele lokalne, OneDrive,
REM  zaleznosci, logowania (chmura/personalne/Meta/Gmail...) i raport stanu.
REM
REM  Wskazowka: na zupelnie swiezej maszynie kliknij PRAWYM -> "Uruchom jako
REM  administrator" (czesc instalatorow tego wymaga). Inaczej dziala per-user.
REM ============================================================================
chcp 65001 > nul
echo.
echo === Przygotowanie srodowiska - Wirtualny Pracownik AI ===
echo To potrwa (instalacje + pobieranie modeli lokalnych). Postepuj wg krokow.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0przygotuj-srodowisko.ps1" %*
echo.
echo === Zakonczono. Okno mozna zamknac. ===
pause
