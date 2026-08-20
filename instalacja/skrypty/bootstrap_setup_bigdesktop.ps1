# Konfiguracja sesji Windows Server pod agenta pracujacego na WIELU OKNACH:
#  - wylacza wygaszacz, blokade i limity czasu sesji (zeby pulpit nie gasl),
#  - DPI 100% (inaczej wspolrzedne klikniec sie rozjezdzaja),
#  - wylacza usypianie ekranu/dyskow (powercfg).
# Plus wypisuje kroki, ktorych NIE da sie ustawic po stronie serwera (duza
# rozdzielczosc + anty-czarny-ekran po stronie KLIENTA RDP).
#
# NAJWAZNIEJSZE (czarne screeny): agent musi dzialac WEWNATRZ sesji na serwerze,
# a RDP sluzyc tylko do podgladu. Po odlaczeniu klienta pulpit sesji przestaje
# sie renderowac i zwykle zrzuty czernieja. Nasz screenshot_capture uzywa
# PrintWindow/DWM (odporny na to), ale i tak trzymaj sesje "zywa" (patrz nizej).
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_setup_bigdesktop.ps1
$ErrorActionPreference = "Continue"

Write-Host "=== Konfiguracja sesji pod prace na wielu oknach ===" -ForegroundColor Cyan

function Set-Reg($path, $name, $value, $type) {
    try {
        if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }
        New-ItemProperty -Path $path -Name $name -Value $value -PropertyType $type -Force | Out-Null
        Write-Host "  [ok] $path\$name = $value"
    } catch { Write-Host "  [uwaga] $path\$name : $($_.Exception.Message)" -ForegroundColor Yellow }
}

# 1. Wygaszacz + blokada wylaczone (pulpit ma sie renderowac non-stop).
Set-Reg "HKCU:\Control Panel\Desktop" "ScreenSaveActive" "0" "String"
Set-Reg "HKCU:\Control Panel\Desktop" "ScreenSaveTimeOut" "0" "String"
Set-Reg "HKCU:\Control Panel\Desktop" "ScreenSaverIsSecure" "0" "String"
Set-Reg "HKCU:\Software\Microsoft\Windows\CurrentVersion\Policies\System" "DisableLockWorkstation" 1 "DWord"
# Limit bezczynnosci maszyny (0 = brak).
Set-Reg "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System" "InactivityTimeoutSecs" 0 "DWord"

# 2. DPI 100% (LogPixels 96). Wymaga wylogowania/zalogowania.
Set-Reg "HKCU:\Control Panel\Desktop" "LogPixels" 96 "DWord"
Set-Reg "HKCU:\Control Panel\Desktop" "Win8DpiScaling" 1 "DWord"

# 3. Nie usypiaj ekranu/dyskow (zasilanie sieciowe).
foreach ($cmd in @("monitor-timeout-ac 0", "standby-timeout-ac 0", "disk-timeout-ac 0")) {
    try { Start-Process powercfg -ArgumentList "/change $cmd" -NoNewWindow -Wait } catch {}
}
Write-Host "  [ok] powercfg: bez usypiania ekranu/dyskow"

Write-Host "`n=== Kroki, ktore musisz zrobic PO STRONIE KLIENTA / recznie ===" -ForegroundColor Cyan
Write-Host @"
  DUZY PULPIT (zeby zmiescic ~16 okien w pelnym rozmiarze):
    - plik .rdp z desktopwidth/desktopheight (np. 7680 x 4320), albo
    - mstsc /multimon (do 16 monitorow = duzy laczony pulpit), albo
    - sterownik wirtualnego monitora (IddSampleDriver / usbmmidd) na sesji konsolowej.
    Siatka 4x4 na 7680x4320 = 16 okien po Full HD (multi_window.plan_grid liczy to samo).

  ANTY-CZARNY-EKRAN (po stronie maszyny, z ktorej sie laczysz przez RDP):
    reg add "HKCU\SOFTWARE\Microsoft\Terminal Server Client" /v RemoteDesktop_SuppressWhenMinimized /t REG_DWORD /d 2 /f
    Albo po zalogowaniu na serwerze przerzuc sesje na konsole (przezyje zamkniecie klienta):
    query session   ; potem:   tscon <ID> /dest:console

  UWAGA: Power BI Desktop je 1-3 GB RAM na instancje - realnie 3-4 na sesje (nie 16).
"@
Write-Host "Gotowe. Wyloguj sie i zaloguj ponownie, zeby DPI 100% zadzialalo." -ForegroundColor Green
exit 0
