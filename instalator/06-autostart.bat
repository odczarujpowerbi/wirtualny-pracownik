@echo off
chcp 65001 >nul
title 06 - Autostart

REM Ten krok rejestruje zadanie w Harmonogramie zadan Windows, co wymaga
REM uprawnien administratora. Jesli okno nie jest administratorem, podnosimy
REM je automatycznie (pojawi sie pytanie systemu o zgode).
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Ten krok wymaga administratora. Uruchamiam ponownie jako administrator...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs -Wait"
  exit /b
)

setlocal
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)
set "APP=%CD%"

echo ============================================================
echo   KROK 06: Autostart (Harmonogram zadan Windows)
echo   Scheduler wstanie sam po zalogowaniu i bedzie chodzil w tle.
echo ============================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\bootstrap_register_task.ps1" -AppPath "%APP%"
if errorlevel 1 (
  echo.
  echo [BLAD] Rejestracja zadania sie nie powiodla.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)
echo.
echo [OK] Zadanie autostartu zarejestrowane i uruchomione.
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
