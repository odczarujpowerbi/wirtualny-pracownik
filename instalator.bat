@echo off
chcp 65001 >nul
title Instalator - Wirtualny Pracownik AI

REM Podnosimy uprawnienia RAZ, na starcie, zeby CALY instalator (lacznie z
REM krokiem 06 - autostart) dzialal w JEDNYM oknie, bez wyskakujacych okien.
REM Jesli okno nie jest administratorem, otwieramy je ponownie jako admin i
REM to nowe okno prowadzi caly proces do konca.
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Podnosze uprawnienia do administratora - potwierdz pytanie systemu Windows...
  powershell -NoProfile -Command "try { Start-Process -FilePath '%~f0' -Verb RunAs } catch { exit 1 }"
  if errorlevel 1 (
    echo.
    echo [UWAGA] Nie udalo sie uruchomic jako administrator (odmowa zgody?).
    echo Kliknij prawym przyciskiem na instalator.bat i wybierz
    echo "Uruchom jako administrator".
    echo.
    pause
  )
  exit /b
)

setlocal
set "KROKI=%~dp0instalator"

echo ============================================================
echo   INSTALATOR - Wirtualny Pracownik AI
echo.
echo   Przejdzie po kolei przez kroki 01-06, w tym jednym oknie.
echo   To, co juz masz zainstalowane, zostanie pominiete.
echo   Okno zostanie otwarte przez caly czas - nie zamykaj go.
echo ============================================================
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
