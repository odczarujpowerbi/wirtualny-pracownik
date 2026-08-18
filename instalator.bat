@echo off
chcp 65001 >nul
setlocal
title Instalator - Wirtualny Pracownik AI

set "KROKI=%~dp0instalator"

echo ============================================================
echo   INSTALATOR - Wirtualny Pracownik AI
echo.
echo   Przejdzie po kolei przez kroki 01-06.
echo   To, co juz masz zainstalowane, zostanie pominiete.
echo ============================================================
echo.
echo   WAZNE: najlepiej uruchom ten instalator jako administrator
echo   (krok 06 - autostart - tego wymaga; sam o to poprosi, jesli nie).
echo.
pause
echo.

call "%KROKI%\01-programy-podstawowe.bat" FROMMASTER
if errorlevel 1 goto :stop
echo.
call "%KROKI%\02-biblioteki-python.bat" FROMMASTER
if errorlevel 1 goto :stop
echo.
call "%KROKI%\03-klucze-dostepowe.bat" FROMMASTER
if errorlevel 1 goto :stop
echo.
call "%KROKI%\04-test-dymny.bat" FROMMASTER
if errorlevel 1 goto :stop
echo.
call "%KROKI%\05-rola-maszyny.bat" FROMMASTER
if errorlevel 1 goto :stop
echo.
call "%KROKI%\06-autostart.bat" FROMMASTER
if errorlevel 1 goto :stop

echo.
echo ============================================================
echo   GOTOWE. Wszystkie kroki przeszly.
echo   Wirtualny pracownik chodzi juz w tle (autostart).
echo ============================================================
echo.
choice /C TN /M "Otworzyc teraz okno podgladu (dashboard)"
if errorlevel 2 goto :koniec
call "%KROKI%\07-uruchom.bat" FROMMASTER
goto :koniec

:stop
echo.
echo ============================================================
echo   ZATRZYMANO. Ktorys krok wymaga uwagi - przeczytaj komunikat
echo   powyzej. Napraw i uruchom instalator ponownie: pominie to,
echo   co juz zrobione (kroki sa idempotentne).
echo ============================================================

:koniec
echo.
pause
