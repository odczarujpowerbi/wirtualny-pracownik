@echo off
chcp 65001 >nul
setlocal

REM ============================================================
REM  Aktualizacja repo z GitHub — dwuklik na maszynie wirtualnej.
REM  Pobiera najswiezsza wersje kodu z galezi main (git pull).
REM  Plik lezy w korzeniu repo, wiec dziala z dowolnego miejsca.
REM ============================================================

cd /d "%~dp0"

echo ============================================================
echo   Aktualizacja: Wirtualny pracownik AI
echo   Katalog: %CD%
echo ============================================================
echo.

REM Czy git jest dostepny?
where git >nul 2>nul
if errorlevel 1 (
    echo [BLAD] Nie znaleziono gita. Zainstaluj gita albo uruchom bootstrap_install_git.ps1.
    echo.
    pause
    exit /b 1
)

REM Czy to na pewno repozytorium git?
git rev-parse --is-inside-work-tree >nul 2>nul
if errorlevel 1 (
    echo [BLAD] Ten folder nie jest repozytorium git. Sklonuj repo najpierw ^(bootstrap_install.ps1^).
    echo.
    pause
    exit /b 1
)

echo Biezaca wersja lokalna:
git log --oneline -1
echo.
echo Pobieram zmiany z GitHub ^(origin/main^)...
echo.

REM --ff-only: tylko czyste przewiniecie do przodu. Jesli ktos robil lokalne
REM commity na VM, pull sie zatrzyma z jasnym komunikatem zamiast tworzyc
REM przypadkowy merge — VM ma tylko konsumowac kod, nie tworzyc.
git pull --ff-only origin main
if errorlevel 1 (
    echo.
    echo [BLAD] Nie udalo sie pobrac zmian.
    echo   - Sprawdz polaczenie z internetem.
    echo   - Jesli sa lokalne zmiany na tej maszynie, cofnij je: git reset --hard origin/main
    echo     ^(UWAGA: to skasuje lokalne zmiany w kodzie; pliki w runs/ i secrets/ sa poza gitem^).
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Gotowe. Aktualna wersja:
git log --oneline -1
echo ============================================================
echo.
pause
