# Instalacja lokalnego modelu AI (Ollama): model WIZYJNY "sterujący ekranem"
# (computer use — krok 4 hierarchii wykonania: API/MCP -> CLI/skrypt -> UI ->
# computer use) oraz model TEKSTOWY do drugiej opinii w validator_prompt.py.
#
# UWAGA: modele wizyjne to kilka GB pobierania i wymagają sensownego RAM/GPU.
# Dlatego w bootstrap_all.ps1 to krok OPCJONALNY (włącz przełącznikiem
# -WithLocalModel). Można też uruchomić ten skrypt samodzielnie, kiedykolwiek.
#
# Nazwy modeli to parametry — biblioteka: https://ollama.com/library
#
# Użycie:
#   .\bootstrap_install_local_model.ps1
#   .\bootstrap_install_local_model.ps1 -VisionModel llama3.2-vision -TextModel hermes3
#   .\bootstrap_install_local_model.ps1 -SkipModels   # sama instalacja Ollamy

param(
    # Model wizyjny sterujący ekranem (computer use). OLLAMA_VISION_MODEL w .env.
    [string]$VisionModel = "llama3.2-vision",

    # Model tekstowy — druga opinia w validator_prompt.py. OLLAMA_TEXT_MODEL w .env.
    [string]$TextModel = "hermes3",

    [switch]$SkipModels
)

$ErrorActionPreference = "Stop"

function Test-CommandExists($name) {
    return $null -ne (Get-Command $name -ErrorAction SilentlyContinue)
}

Write-Host "=== Lokalny model AI (Ollama) ===" -ForegroundColor Cyan

if (Test-CommandExists "ollama") {
    Write-Host "Ollama już zainstalowana."
} else {
    Write-Host "Instaluję Ollama..."
    $installed = $false
    if (Test-CommandExists "winget") {
        winget install --id Ollama.Ollama --silent --accept-source-agreements --accept-package-agreements
        if ($LASTEXITCODE -eq 0) { $installed = $true }
    }
    if (-not $installed) {
        # Fallback: oficjalny instalator, cicha instalacja.
        $setup = Join-Path $env:TEMP "OllamaSetup.exe"
        Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup
        Start-Process -FilePath $setup -ArgumentList "/VERYSILENT" -Wait
    }
    # Odśwież PATH w tej sesji, żeby 'ollama' było widoczne od razu po instalacji.
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
    if (-not (Test-CommandExists "ollama")) {
        Write-Error "Ollama zainstalowana, ale 'ollama' nie jest w PATH tej sesji. Zamknij i otwórz PowerShell, potem uruchom ten skrypt ponownie (pobierze same modele)."
        exit 1
    }
}

if ($SkipModels) {
    Write-Host "Pominięto pobieranie modeli (-SkipModels)."
    exit 0
}

# Ollama serwuje lokalnie na http://localhost:11434 (validator_prompt.py oraz
# przyszły worker computer use). `ollama pull` sam startuje usługę w tle.
foreach ($model in @($VisionModel, $TextModel)) {
    Write-Host "`nPobieram model: $model (to może potrwać, kilka GB)..." -ForegroundColor Cyan
    ollama pull $model
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Pobranie modelu '$model' nie powiodło się (kod $LASTEXITCODE). Sprawdź nazwę na https://ollama.com/library i połączenie sieciowe."
        exit 1
    }
}

Write-Host "`n=== Gotowe ===" -ForegroundColor Green
Write-Host "Model wizyjny (ekran):    $VisionModel"
Write-Host "Model tekstowy (walidator): $TextModel"
Write-Host "Endpoint: http://localhost:11434"
Write-Host "W secrets\.env ustaw (opcjonalnie): OLLAMA_HOST, OLLAMA_VISION_MODEL, OLLAMA_TEXT_MODEL"
