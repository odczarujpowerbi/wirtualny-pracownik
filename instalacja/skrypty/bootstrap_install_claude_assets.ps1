# Provisioning zasobow Claude Code na maszynie (VM): odtwarza GLOBALNY ~/.claude
# tak, zeby agent mial ten sam zestaw co maszyna glowna:
#   - skille (~/.claude/skills) z biblioteki OneDrive "Aplikacje Claude - Documents/skills"
#   - agenci ogolni (~/.claude/agents) z ".../agents" (dev-expert, power-bi-expert, koordynator...)
#   - pluginy przez marketplace (claude plugin): power-bi-agentic-development, claude-plugins-official,
#     claude-powerline, oaustegard-claude-skills
#
# CZEGO NIE RUSZAMY: agenci-PERSONY (Odczaruj / Clickless) sa per-projekt w
# folderach "Buyer persony ..." i synchronizuja sie na VM przez OneDrive - zostaja
# projektowe (oba maja np. persona-tomek, wiec globalnie by kolidowaly).
#
# Zrodlo (biblioteka) jest na OneDrive - wiec na VM MUSI byc zalogowany i
# zsynchronizowany OneDrive (bootstrap_setup_onedrive.ps1 to robi).
#
# Idempotentny: istniejace skille/agentow pomija (chyba ze -Force). Pluginy
# instaluje best-effort (moga wymagac zalogowanego 'claude' i potwierdzenia
# zaufania marketplace) - pominiesz je flaga -SkipPlugins.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:
#   powershell -ExecutionPolicy Bypass -File bootstrap_install_claude_assets.ps1
#   ... -LibraryRoot "<sciezka do 'Aplikacje Claude - Documents'>"   ... -Force   ... -SkipPlugins
param(
    [string]$LibraryRoot,
    [switch]$Force,
    [switch]$SkipPlugins
)
$ErrorActionPreference = "Stop"
$claudeHome = Join-Path $env:USERPROFILE ".claude"

function Find-Under($name, $depth) {
    # Pierwszy katalog o danej nazwie pod profilem uzytkownika (tam siedzi OneDrive).
    $hit = Get-ChildItem -Path $env:USERPROFILE -Directory -Recurse -Depth $depth -Filter $name -ErrorAction SilentlyContinue |
        Select-Object -First 1
    return $hit.FullName
}

function Copy-Assets($src, $dstRoot, $label) {
    if (-not (Test-Path $src)) { Write-Host "  [pomijam] brak zrodla: $src" -ForegroundColor Yellow; return }
    New-Item -ItemType Directory -Path $dstRoot -Force | Out-Null
    $copied = 0; $skipped = 0
    foreach ($item in Get-ChildItem -Path $src) {
        $target = Join-Path $dstRoot $item.Name
        if ((Test-Path $target) -and -not $Force) { $skipped++; continue }
        Copy-Item $item.FullName $target -Recurse -Force
        $copied++
    }
    Write-Host ("  {0}: skopiowano {1}, pominieto (juz sa) {2}" -f $label, $copied, $skipped) -ForegroundColor Green
}

function Find-Claude {
    $c = Get-Command claude -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    foreach ($p in @("$env:USERPROFILE\.local\bin\claude.exe", "$env:USERPROFILE\.local\bin\claude")) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

Write-Host "=== Provisioning zasobow Claude Code (skille / agenci / pluginy) ===" -ForegroundColor Cyan

# 1. Znajdz biblioteke na OneDrive.
if (-not $LibraryRoot) { $LibraryRoot = Find-Under "Aplikacje Claude - Documents" 4 }
if (-not $LibraryRoot -or -not (Test-Path $LibraryRoot)) {
    Write-Error "Nie znalazlem 'Aplikacje Claude - Documents' pod profilem. Zaloguj/zsynchronizuj OneDrive albo podaj -LibraryRoot."
    exit 1
}
Write-Host "Biblioteka: $LibraryRoot"

# 2. Skille i agenci ogolni -> ~/.claude.
Write-Host "`n[1/3] Skille -> $claudeHome\skills"
Copy-Assets (Join-Path $LibraryRoot "skills") (Join-Path $claudeHome "skills") "skille"
Write-Host "[2/3] Agenci ogolni -> $claudeHome\agents"
Copy-Assets (Join-Path $LibraryRoot "agents") (Join-Path $claudeHome "agents") "agenci"

# 3. Pluginy przez marketplace (best-effort).
Write-Host "`n[3/3] Pluginy (marketplace + instalacja)"
if ($SkipPlugins) {
    Write-Host "  Pominieto (-SkipPlugins)."
} else {
    $claude = Find-Claude
    if (-not $claude) {
        Write-Host "  [pomijam] 'claude' niedostepny - zaloguj Claude Code i uruchom ponownie (albo -SkipPlugins)." -ForegroundColor Yellow
    } else {
        # Marketplace power-bi-agentic-development to KATALOG na OneDrive (Edukacja).
        $pbiMkt = Find-Under "power-bi-agentic-development" 6
        $marketplaces = @("anthropics/claude-plugins-official", "Owloops/claude-powerline",
                          "https://github.com/oaustegard/claude-skills.git")
        if ($pbiMkt) { $marketplaces += $pbiMkt } else {
            Write-Host "  [uwaga] nie znalazlem katalogu 'power-bi-agentic-development' (Edukacja) - pomijam ten marketplace." -ForegroundColor Yellow
        }
        foreach ($m in $marketplaces) {
            Write-Host "  marketplace add: $m"
            try { & $claude plugin marketplace add $m 2>&1 | Out-Host } catch { Write-Host "    [uwaga] $($_.Exception.Message)" -ForegroundColor Yellow }
        }
        $plugins = @(
            "claude-powerline@claude-powerline",
            "pbip@power-bi-agentic-development", "fabric-cli@power-bi-agentic-development",
            "fabric-admin@power-bi-agentic-development", "pbi-desktop@power-bi-agentic-development",
            "reports@power-bi-agentic-development", "semantic-models@power-bi-agentic-development",
            "tabular-editor@power-bi-agentic-development",
            "code-review@claude-plugins-official", "claude-md-management@claude-plugins-official",
            "code-simplifier@claude-plugins-official", "discord@claude-plugins-official",
            "frontend-design@claude-plugins-official"
        )
        foreach ($p in $plugins) {
            Write-Host "  plugin install: $p"
            try { & $claude plugin install $p 2>&1 | Out-Host } catch { Write-Host "    [uwaga] $($_.Exception.Message)" -ForegroundColor Yellow }
        }
    }
}

Write-Host "`n=== Gotowe ===" -ForegroundColor Green
Write-Host "Skille i agenci ogolni w $claudeHome. Persony (Odczaruj/Clickless) zostaja per-projekt w folderach 'Buyer persony ...' (OneDrive)."
exit 0
