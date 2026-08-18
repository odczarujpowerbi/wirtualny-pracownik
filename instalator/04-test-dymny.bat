@echo off
chcp 65001 >nul
setlocal
title 04 - Test dymny
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)

echo ============================================================
echo   KROK 04: Test dymny (sprawdza mechanizm przed praca)
echo ============================================================
echo.
python bootstrap_smoke_test.py
if errorlevel 1 (
  echo.
  echo [BLAD] Test dymny nie przeszedl. Skopiuj caly komunikat powyzej.
  popd
  if not "%~1"=="FROMMASTER" pause
  exit /b 1
)
echo.
echo [OK] Test dymny przeszedl.
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
