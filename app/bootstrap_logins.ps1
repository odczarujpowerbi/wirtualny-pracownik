# Przewodnik po logowaniach - interaktywny checklist kont potrzebnych agentowi.
# Nie wszystko da sie zrobic przez API: czesc pracy idzie przez interfejs
# (Meta, Gmail), a VS Code / Claude Code loguje sie raz na konto. Ten skrypt
# prowadzi krok po kroku: pokazuje CO zrobic, otwiera odpowiednia aplikacje/URL,
# czeka na potwierdzenie i zapisuje stan do runs/logins_status.json.
#
# Konta (dwa profile logowania wg ustalen):
#   - KONTO CHMUROWE (firmowe) - Microsoft 365 / OneDrive, glowny profil pracy.
#   - KONTO PERSONALNE - drugi profil w VS Code (Settings Sync / GitHub).
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:
#   powershell -ExecutionPolicy Bypass -File bootstrap_logins.ps1
#   ... -NonInteractive   # tylko wypisz liste, nic nie otwieraj i nie czekaj
param([switch]$NonInteractive)

$ErrorActionPreference = "Stop"
$statusPath = Join-Path $PSScriptRoot "runs\logins_status.json"

# Kazda pozycja: nazwa, instrukcja, opcjonalny URL do otwarcia w przegladarce
# albo aplikacja do uruchomienia.
$logins = @(
    @{ Key = "claude_code";   Name = "Claude Code (CLI)";
       Info = "W terminalu wpisz: claude   i zaloguj sie na subskrypcje. To naped glownego modelu agenta." }
    @{ Key = "vscode_cloud";  Name = "VS Code - konto CHMUROWE (firmowe)";
       Info = "Otworz VS Code, prawy dolny rog -> Accounts -> Sign in. Zaloguj konto firmowe (Microsoft 365).";
       App = "code" }
    @{ Key = "vscode_personal"; Name = "VS Code - konto PERSONALNE";
       Info = "W VS Code dodaj drugie konto (Accounts -> Sign in) - personalne, do Settings Sync / GitHub." }
    @{ Key = "microsoft365";  Name = "Microsoft 365 (chmura) w przegladarce";
       Info = "Zaloguj konto firmowe - mail, SharePoint, OneDrive. Czesc pracy idzie przez interfejs, nie tylko API.";
       Url = "https://www.office.com/" }
    @{ Key = "gmail";         Name = "Gmail / Google (przegladarka)";
       Info = "Zaloguj konto Google. Potrzebne, bo nie wszystko robimy przez API - czasem trzeba przez interfejs.";
       Url = "https://accounts.google.com/" }
    @{ Key = "meta_business"; Name = "Meta Business (przegladarka)";
       Info = "Zaloguj Business Manager - kampanie i zmiany, ktore robimy przez interfejs Meta.";
       Url = "https://business.facebook.com/" }
    @{ Key = "github";        Name = "GitHub (repozytoria stron)";
       Info = "Zaloguj GitHub w przegladarce i/lub w VS Code - repozytoria stron internetowych.";
       Url = "https://github.com/login" }
)

function Load-Status {
    if (Test-Path $statusPath) {
        try { return (Get-Content $statusPath -Raw | ConvertFrom-Json) } catch { return $null }
    }
    return $null
}

function Save-Status($done) {
    New-Item -ItemType Directory -Path (Split-Path $statusPath) -Force | Out-Null
    @{ updated_at = (Get-Date).ToString("o"); confirmed = $done } |
        ConvertTo-Json -Depth 4 | Set-Content -Path $statusPath -Encoding UTF8
}

Write-Host "=== Przewodnik po logowaniach ==="
Write-Host "Dwa profile: KONTO CHMUROWE (firmowe) oraz KONTO PERSONALNE."
Write-Host ""

if ($NonInteractive) {
    foreach ($l in $logins) {
        Write-Host ("- {0}" -f $l.Name)
        Write-Host ("    {0}" -f $l.Info)
        if ($l.Url) { Write-Host ("    URL: {0}" -f $l.Url) }
    }
    Write-Host "`n(Tryb NonInteractive - nic nie otwarto. Uruchom bez -NonInteractive, zeby przejsc krok po kroku.)"
    exit 0
}

$done = @()
$num = 0
foreach ($l in $logins) {
    $num++
    Write-Host ("`n[$num/$($logins.Count)] $($l.Name)") -ForegroundColor Cyan
    Write-Host ("    $($l.Info)")
    if ($l.Url) {
        Write-Host ("    Otwieram: $($l.Url)")
        Start-Process $l.Url
    } elseif ($l.App) {
        if (Get-Command $l.App -ErrorAction SilentlyContinue) { Start-Process $l.App }
    }
    $ans = Read-Host "    Zalogowane? [t=tak / p=pomin / q=przerwij]"
    if ($ans -eq "q") { Write-Host "Przerwano."; break }
    if ($ans -eq "t") { $done += $l.Key; Write-Host "    OK" -ForegroundColor Green }
    else { Write-Host "    Pominieto" -ForegroundColor Yellow }
}

Save-Status $done
Write-Host "`nZapisano stan logowan: $statusPath"
Write-Host "Potwierdzone: $($done.Count)/$($logins.Count)"
exit 0
