@echo off
chcp 65001 >nul
setlocal
title 05 - Rola maszyny
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)

echo ============================================================
echo   KROK 05: Rola tej maszyny
echo ============================================================
echo.
echo Dostepne role:
python bootstrap_register.py
echo.
set "ROLA="
set /p "ROLA=Wpisz nazwe roli (np. dev) i nacisnij Enter: "
if "%ROLA%"=="" (
  echo [BLAD] Nie podano roli.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)
python bootstrap_register.py %ROLA%
if errorlevel 1 (
  echo.
  echo [BLAD] Rejestracja roli sie nie powiodla.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)
echo.
echo [OK] Zarejestrowano role: %ROLA%
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
