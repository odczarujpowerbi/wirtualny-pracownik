@echo off
chcp 65001 >nul
setlocal
title 07 - Uruchom (dashboard)
pushd "%~dp0..\app" 2>nul || (echo [BLAD] Nie znaleziono folderu app obok instalatora. & pause & exit /b 1)

echo ============================================================
echo   KROK 07: Podglad na zywo (dashboard)
echo   Otwiera http://127.0.0.1:8787/ w przegladarce.
echo   Zostaw to okno otwarte - zamkniecie okna zamyka dashboard.
echo   (Ctrl+C konczy dashboard.)
echo ============================================================
echo.
python dashboard.py
popd
if not "%~1"=="FROMMASTER" pause
exit /b 0
