@echo off
chcp 65001 >nul
setlocal
title 01 - Programy podstawowe
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)
set "APP=%CD%"

echo ============================================================
echo   KROK 01: Programy podstawowe (Git, Python, Claude Code)
echo   Sprawdzam co juz jest. Pomijam zainstalowane.
echo ============================================================
echo.
set "NOWE=0"

where git >nul 2>nul
if errorlevel 1 (
  echo [ ] Git - brak. Instaluje...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\bootstrap_install_git.ps1"
  set "NOWE=1"
) else (
  for /f "delims=" %%v in ('git --version') do echo [OK] Git juz jest: %%v
)

where python >nul 2>nul
if errorlevel 1 (
  echo [ ] Python - brak. Instaluje...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\bootstrap_install_python.ps1"
  set "NOWE=1"
) else (
  for /f "delims=" %%v in ('python --version') do echo [OK] Python juz jest: %%v
)

where claude >nul 2>nul
if errorlevel 1 (
  echo [ ] Claude Code - brak. Instaluje (opcjonalny)...
  powershell -NoProfile -ExecutionPolicy Bypass -File "%APP%\bootstrap_install_claude_code.ps1"
  set "NOWE=1"
) else (
  echo [OK] Claude Code juz jest.
)

echo.
if "%NOWE%"=="1" (
  echo UWAGA: cos zostalo wlasnie zainstalowane.
  echo Zamknij to okno i uruchom instalator PONOWNIE, zeby system
  echo zobaczyl nowe programy w nowym oknie.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)

echo Wszystkie programy podstawowe sa na miejscu.
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
