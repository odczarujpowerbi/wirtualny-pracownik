# Mini-raport stanu srodowiska: co jest zainstalowane i (na ile da sie wykryc)
# zalogowane na TEJ maszynie. Sluzy jako "zdjecie konfiguracji" - punkt odniesienia
# przy stawianiu kolejnej maszyny. Wynik na ekran ORAZ do pliku (domyslnie
# instalacja/STAN-SRODOWISKA.txt).
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_env_report.ps1 [-OutFile sciezka]
param([string]$OutFile)

$ErrorActionPreference = "Continue"

function Ver($cmd, $verArg) {
    # UWAGA: parametr NIE moze nazywac sie $args - to zmienna automatyczna PS
    # (tablica niezwiazanych argumentow) i wtedy flaga nie trafia do polecenia.
    if (Get-Command $cmd -ErrorAction SilentlyContinue) {
        try {
            $out = & $cmd $verArg 2>&1 | Where-Object { "$_".Trim() -ne "" } | Select-Object -First 1
            if ($out) { return "$out" } else { return "obecny (wersja nieznana)" }
        } catch { return "obecny (wersja nieznana)" }
    }
    return "BRAK"
}

$lines = @()
$lines += "=== STAN SRODOWISKA - Wirtualny Pracownik AI ==="
$lines += "Maszyna: $env:COMPUTERNAME    Uzytkownik: $env:USERNAME"
$lines += "Data:    $((Get-Date).ToString('yyyy-MM-dd HH:mm'))"
$lines += ""
$lines += "-- Narzedzia --"
$lines += "Git:          $(Ver 'git' '--version')"
$lines += "Python:       $(Ver 'python' '--version')"
$lines += "Node.js:      $(Ver 'node' '--version')"
$lines += "Claude Code:  $(Ver 'claude' '--version')"
$lines += "VS Code:      $(Ver 'code' '--version')"

# Rozszerzenia VS Code (czy jest Claude Code).
if (Get-Command code -ErrorAction SilentlyContinue) {
    $ext = (code --list-extensions 2>&1)
    $hasClaude = ($ext -match "claude") -join ", "
    $lines += "  Rozszerzenie Claude Code: $(if ($hasClaude) { $hasClaude } else { 'BRAK - dodaj: code --install-extension anthropic.claude-code' })"
}

# Microsoft Office / 365 Apps (Excel, Word).
$officeVer = $null
if (Test-Path "HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration") {
    try { $officeVer = (Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Office\ClickToRun\Configuration").VersionToReport } catch {}
    $lines += "Office:       obecny (Click-to-Run$(if ($officeVer) { ", $officeVer" }))"
} elseif ((Test-Path "$env:ProgramFiles\Microsoft Office\root\Office16\EXCEL.EXE") -or (Test-Path "${env:ProgramFiles(x86)}\Microsoft Office\root\Office16\EXCEL.EXE")) {
    $lines += "Office:       obecny (Excel/Word wykryte)"
} else {
    $lines += "Office:       BRAK (Excel/Word - bootstrap_install_office.ps1)"
}

# Ollama (modele lokalne).
if (Get-Command ollama -ErrorAction SilentlyContinue) {
    $models = (ollama list 2>&1 | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] }) -join ", "
    $lines += "Ollama:       obecny. Modele: $(if ($models) { $models } else { 'brak pobranych' })"
} else {
    $lines += "Ollama:       BRAK (modele lokalne - bootstrap_install_local_model.ps1)"
}

$lines += ""
$lines += "-- OneDrive --"
if ($env:OneDrive -and (Test-Path $env:OneDrive)) {
    $lines += "Sync:         OK -> $env:OneDrive"
} else {
    $lines += "Sync:         niezalogowany / brak folderu (bootstrap_setup_onedrive.ps1)"
}

$lines += ""
$lines += "-- Logowania (ostatni potwierdzony checklist) --"
$loginStatus = Join-Path $PSScriptRoot "runs\logins_status.json"
if (Test-Path $loginStatus) {
    $s = Get-Content $loginStatus -Raw | ConvertFrom-Json
    $lines += "Potwierdzono: $($s.confirmed -join ', ')"
    $lines += "Aktualizacja: $($s.updated_at)"
} else {
    $lines += "Brak zapisu - uruchom bootstrap_logins.ps1"
}

$text = $lines -join "`r`n"
Write-Host $text

if (-not $OutFile) {
    $OutFile = Join-Path (Split-Path $PSScriptRoot -Parent) "instalacja\STAN-SRODOWISKA.txt"
}
New-Item -ItemType Directory -Path (Split-Path $OutFile) -Force | Out-Null
Set-Content -Path $OutFile -Value $text -Encoding UTF8
Write-Host "`nZapisano: $OutFile"
exit 0
