# Instaluje aplikacje BEZ winget - bezposrednie instalatory (na Windows Server
# winget czesto sie NIE da doinstalowac: brak frameworka WindowsAppRuntime,
# HRESULT 0x80073CF3 - realnie napotkane). Wykrywanie "czy juz jest" przez
# rejestr (Uninstall) + Appx, wiec ponowne uruchomienie pomija zainstalowane.
#
# Tradycyjne instalatory .exe/.msi (Power BI, Chrome, Obsidian) instaluja sie
# bez Sklepu/winget. Aplikacje typu Store/MSIX (nowy Teams, nowy Outlook) sa
# trudne headless na Server - dajemy jasna notke recznej instalacji zamiast
# marnowac czas na proby, ktore i tak padna.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_install_apps.ps1
$ErrorActionPreference = "Continue"

Write-Host "=== Aplikacje (bezposrednie instalatory, bez winget) ==="

function Test-AppInstalled([string[]]$patterns) {
    # Dopasowanie po DOWOLNYM z podanych wzorcow - wersje Store/MSIX maja inne
    # nazwy niz klasyczne (np. Appx 'MicrosoftPowerBIDesktop' vs DisplayName
    # 'Power BI Desktop'), wiec podajemy oba warianty.
    $keys = @(
        "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*",
        "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*"
    )
    $reg = foreach ($k in $keys) { Get-ItemProperty $k -ErrorAction SilentlyContinue }
    $appx = Get-AppxPackage -ErrorAction SilentlyContinue
    foreach ($p in $patterns) {
        if ($reg  | Where-Object { $_.DisplayName -like "*$p*" }) { return $true }
        if ($appx | Where-Object { $_.Name -like "*$p*" }) { return $true }
    }
    return $false
}

function Install-FromUrl($name, $url, $file, $silentArgs) {
    $path = Join-Path $env:TEMP $file
    Write-Host "  pobieram $name..."
    Invoke-WebRequest -Uri $url -OutFile $path -UseBasicParsing
    Write-Host "  instaluje $name (cicho)..."
    if ($file -match "\.msi$") {
        Start-Process msiexec.exe -ArgumentList (@("/i", "`"$path`"") + $silentArgs) -Wait
    } else {
        Start-Process -FilePath $path -ArgumentList $silentArgs -Wait
    }
}

$fail = 0

# --- Power BI Desktop (rdzen projektu) - bezposredni instalator ---
if (Test-AppInstalled @("Power BI Desktop","PowerBIDesktop")) {
    Write-Host "Power BI Desktop juz jest - pomijam."
} else {
    try { Install-FromUrl "Power BI Desktop" "https://aka.ms/pbiSingleInstaller" "PBIDesktopSetup_x64.exe" @("-quiet","-norestart","ACCEPT_EULA=1"); Write-Host "  OK" }
    catch { Write-Host "  UWAGA Power BI: $($_.Exception.Message)"; $fail++ }
}

# --- Google Chrome - enterprise MSI (cicha instalacja) ---
if (Test-AppInstalled @("Google Chrome","Chrome")) {
    Write-Host "Google Chrome juz jest - pomijam."
} else {
    try { Install-FromUrl "Google Chrome" "https://dl.google.com/tag/s/dl/chrome/install/googlechromestandaloneenterprise64.msi" "chrome.msi" @("/qn","/norestart"); Write-Host "  OK" }
    catch { Write-Host "  UWAGA Chrome: $($_.Exception.Message)"; $fail++ }
}

# --- Obsidian - najnowszy .exe z GitHub Releases (API) ---
if (Test-AppInstalled @("Obsidian")) {
    Write-Host "Obsidian juz jest - pomijam."
} else {
    try {
        $rel = Invoke-RestMethod "https://api.github.com/repos/obsidianmd/obsidian-releases/releases/latest" -Headers @{ "User-Agent" = "wirtualny-pracownik" }
        $asset = $rel.assets | Where-Object { $_.name -match "^Obsidian-.*\.exe$" } | Select-Object -First 1
        if ($asset) { Install-FromUrl "Obsidian" $asset.browser_download_url $asset.name @("/S"); Write-Host "  OK" }
        else { Write-Host "  UWAGA Obsidian: nie znalazlem instalatora .exe w releases"; $fail++ }
    } catch { Write-Host "  UWAGA Obsidian: $($_.Exception.Message)"; $fail++ }
}

# --- Teams / Outlook (nowe) - Store/MSIX, trudne headless na Server ---
foreach ($storeApp in @(
    @{ Name = "Microsoft Teams (nowy)"; Pattern = "Teams";   Note = "https://www.microsoft.com/microsoft-teams/download-app" },
    @{ Name = "Outlook (nowy)";         Pattern = "Outlook"; Note = "Nowy Outlook: Start -> 'Outlook (new)' albo ze Sklepu; klasyczny wchodzi z Office." }
)) {
    if (Test-AppInstalled @($storeApp.Pattern)) { Write-Host "$($storeApp.Name) juz jest - pomijam." }
    else { Write-Host "$($storeApp.Name): aplikacja Store/MSIX - zainstaluj recznie: $($storeApp.Note)" }
}

Write-Host "`nZakonczono aplikacje. Bledow pobierania: $fail. Power BI/Chrome/Obsidian ida bezposrednio; Teams/Outlook recznie."
exit 0
