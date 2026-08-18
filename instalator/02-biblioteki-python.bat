@echo off
chcp 65001 >nul
setlocal
title 02 - Biblioteki Pythona
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)

echo ============================================================
echo   KROK 02: Biblioteki Pythona (pip install)
echo ============================================================
echo.
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo [BLAD] Instalacja bibliotek sie nie powiodla.
  echo Sprawdz, czy Python jest zainstalowany (krok 01) i sprobuj ponownie.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)
echo.
echo [OK] Biblioteki zainstalowane.
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
