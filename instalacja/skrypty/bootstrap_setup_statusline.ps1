# Konfiguruje statuslinie Claude Code (pasek na dole terminala z limitami:
# blok 5h, tydzien, dzis) - claude-powerline (@owloops/claude-powerline), tak jak
# na maszynie referencyjnej. Ustawia "statusLine" w ~/.claude/settings.json
# (MERGE - nie nadpisuje pozostalych ustawien) i dokłada config claude-powerline.json.
#
# Wymaga Node/npx (instalowany wczesniej w bootstrapie - Claude Code idzie przez npm).
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_setup_statusline.ps1
#   ... -ClaudeDir <sciezka>   (do testow - domyslnie ~/.claude)
param(
    [string]$ClaudeDir = (Join-Path $env:USERPROFILE ".claude")
)
$ErrorActionPreference = "Stop"

Write-Host "=== Statuslinia Claude Code (limity: blok 5h / tydzien / dzis) ==="

if (-not (Get-Command npx -ErrorAction SilentlyContinue)) {
    Write-Host "UWAGA: brak 'npx' (Node.js). Zainstaluj Node (jest w bootstrapie) i uruchom ponownie."
    exit 1
}

New-Item -ItemType Directory -Path $ClaudeDir -Force | Out-Null
$settingsPath = Join-Path $ClaudeDir "settings.json"

# 1. MERGE statusLine do settings.json (zachowujemy reszte ustawien).
$settings = [ordered]@{}
if (Test-Path $settingsPath) {
    try {
        $existing = Get-Content $settingsPath -Raw | ConvertFrom-Json
        foreach ($p in $existing.PSObject.Properties) { $settings[$p.Name] = $p.Value }
    } catch {
        Write-Host "UWAGA: settings.json nie parsuje sie ($($_.Exception.Message)) - robie kopie i pisze od nowa."
        Copy-Item $settingsPath "$settingsPath.bak" -Force
    }
}
$settings["statusLine"] = [ordered]@{ type = "command"; command = "npx -y @owloops/claude-powerline@latest" }
$settings | ConvertTo-Json -Depth 10 | Set-Content -Path $settingsPath -Encoding UTF8
Write-Host "Ustawiono statusLine w: $settingsPath"

# 2. Config claude-powerline.json (segmenty limitow) - z dolaczonego szablonu,
#    tylko jesli jeszcze nie ma (nie nadpisujemy recznych zmian uzytkownika).
$plPath = Join-Path $ClaudeDir "claude-powerline.json"
$template = Join-Path $PSScriptRoot "..\claude\claude-powerline.json"
if (Test-Path $plPath) {
    Write-Host "claude-powerline.json juz istnieje - zostawiam bez zmian."
} elseif (Test-Path $template) {
    Copy-Item $template $plPath -Force
    Write-Host "Skopiowano config statuslinii: $plPath"
} else {
    Write-Host "Brak szablonu $template - statuslinia zadziala z domyslna konfiguracja powerline."
}

Write-Host "Gotowe. Pasek pojawi sie na dole w Claude Code (nowa sesja); pokazuje zuzycie bloku 5h, tygodnia i dzis."
exit 0
