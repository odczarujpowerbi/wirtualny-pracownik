@echo off
chcp 65001 >nul
setlocal
title 03 - Klucze dostepowe
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)
set "APP=%CD%"

echo ============================================================
echo   KROK 03: Klucze dostepowe (folder secrets)
echo ============================================================
echo.
python bootstrap_init_secrets.py
if errorlevel 1 (
  echo.
  echo [BLAD] Nie udalo sie utworzyc folderu secrets.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)
echo.
echo Otwieram plik secrets\.env do wpisania kluczy.
echo Wpisz MINIMUM:
echo    ANTHROPIC_API_KEY
echo    PROJECTLY_API_KEY
echo    PROJECTLY_BASE_URL
echo Zapisz plik (Ctrl+S) i zamknij Notatnik, zeby kontynuowac.
echo.
if exist "%APP%\secrets\.env" (
  start /wait notepad "%APP%\secrets\.env"
) else (
  echo [UWAGA] Nie znalazlem secrets\.env - sprawdz recznie folder secrets.
)
echo.
echo [OK] Krok kluczy zakonczony.
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
