@echo off
REM ============================================================================
REM NADZORCA - jedyny proces, ktory ma domyslnie chodzic na tej maszynie
REM (decyzja wlasciciela 01.09.2026). Sam nie wykonuje zadan i nie wola modelu:
REM co 30s czyta status zadania sterujacego kazdej roli w Projectly
REM ("Kontrola bota: <rola>") i odpala proces bota, ktory ma byc wlaczony.
REM
REM Wczesniej bylo odwrotnie: przy zalogowaniu startowala cala czworka botow
REM (start-agent-dev/checker/marketing/zarzad.bat), a zadanie sterujace umialo
REM je tylko WSTRZYMAC - bot musial juz chodzic i zajmowac pamiec, zeby dalo sie
REM nim zdalnie sterowac. Teraz bot wylaczony to bot, ktorego nie ma jako proces.
REM
REM Wlaczanie/wylaczanie bota:
REM   - w Projectly: status zadania "Kontrola bota: <rola>" na Done = wylaczony,
REM     kazdy inny status (todo/in progress) = wlaczony,
REM   - lokalnie: panel operatora (start-dashboard.bat -> http://127.0.0.1:8787/),
REM     panel "Agenci", przyciski Wlacz/Wylacz.
REM
REM Podglad stanu bez uruchamiania petli:  python app\agent_supervisor.py --status
REM
REM Rejestrowany w Harmonogramie zadan Windows przez
REM instalacja\skrypty\register-task-nadzorca.ps1 (wyzwalacz: przy zalogowaniu).
REM Pozostale start-agent-*.bat zostaja - do recznego odpalenia jednego bota
REM z pominieciem nadzorcy (np. przy diagnostyce, z widocznym oknem konsoli).
REM ============================================================================
chcp 65001 > nul
cd /d "%~dp0app"
python agent_supervisor.py
