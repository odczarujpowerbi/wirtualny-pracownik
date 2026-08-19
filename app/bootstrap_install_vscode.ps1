# Instaluje Visual Studio Code + rozszerzenie Claude Code (kodowanie z agentem
# AI wewnatrz edytora). Idempotentne: jesli 'code' juz jest w PATH, pomija
# instalacje i tylko dokłada/aktualizuje rozszerzenie.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_install_vscode.ps1
$ErrorActionPreference = "Stop"

function Test-Command($name) {
    return [bool](Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "=== Visual Studio Code + rozszerzenie do kodowania ==="

if (Test-Command "code") {
    Write-Host "VS Code juz zainstalowany (polecenie 'code' dostepne) - pomijam instalacje."
} else {
    Write-Host "Instaluje VS Code..."
    if (Test-Command "winget") {
        # -e dokladne ID, --scope user nie wymaga admina.
        winget install -e --id Microsoft.VisualStudioCode --scope user --accept-source-agreements --accept-package-agreements
    } else {
        # Fallback: instalator User (per-user, bez admina) z oficjalnego zrodla.
        $installer = Join-Path $env:TEMP "vscode-user-setup.exe"
        Write-Host "winget niedostepny - pobieram instalator User Setup..."
        Invoke-WebRequest -Uri "https://update.code.visualstudio.com/latest/win32-x64-user/stable" -OutFile $installer
        # /VERYSILENT /MERGETASKS=!runcode - cicha instalacja, dodaje 'code' do PATH.
        Start-Process -FilePath $installer -ArgumentList "/VERYSILENT", "/NORESTART", "/MERGETASKS=addtopath" -Wait
    }
    Write-Host "VS Code zainstalowany. Uwaga: nowe okno terminala moze byc potrzebne, zeby 'code' trafil do PATH."
}

# Rozszerzenie Claude Code do VS Code (kodowanie z agentem w edytorze).
if (Test-Command "code") {
    # Najpierw SPRAWDZ, czy juz jest - inaczej --install-extension mieli ~18s przy
    # kazdym przebiegu (uzytkownik: "dlugo sie kreci"). Lista jest szybka.
    $hasExt = $false
    try { $hasExt = ((code --list-extensions 2>&1) -match "anthropic.claude-code").Count -gt 0 } catch { }
    if ($hasExt) {
        Write-Host "Rozszerzenie Claude Code juz jest - pomijam."
    } else {
        Write-Host "Instaluje rozszerzenie Claude Code..."
        try {
            code --install-extension anthropic.claude-code
            Write-Host "Rozszerzenie Claude Code gotowe."
        } catch {
            Write-Host "UWAGA: nie udalo sie zainstalowac rozszerzenia automatycznie ($($_.Exception.Message))."
            Write-Host "Zainstaluj recznie w VS Code: Extensions -> szukaj 'Claude Code'."
        }
    }
} else {
    Write-Host "UWAGA: 'code' jeszcze nie w PATH - zainstaluj rozszerzenie po restarcie terminala:"
    Write-Host "  code --install-extension anthropic.claude-code"
}

Write-Host "Krok VS Code zakonczony."
exit 0
