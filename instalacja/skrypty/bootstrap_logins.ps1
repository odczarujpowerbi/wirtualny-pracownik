# Przewodnik po logowaniach - interaktywny checklist kont potrzebnych agentowi.
# Nie wszystko da sie zrobic przez API: czesc pracy idzie przez interfejs
# (Meta, Gmail), a VS Code / Claude Code loguje sie raz na konto. Ten skrypt
# prowadzi krok po kroku: pokazuje CO zrobic, otwiera odpowiednia aplikacje/URL,
# czeka na potwierdzenie, zamyka otwarte przez siebie okno i zapisuje stan do
# app/runs/logins_status.json.
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
# Stan to plik runtime -> app/runs/ (w .gitignore). NIE do instalacja/skrypty/runs/,
# bo tamta sciezka jest sledzona przez git (konflikt przy git pull - patrz CLAUDE.md).
$statusPath = Join-Path $PSScriptRoot "..\..\app\runs\logins_status.json"

# Procesy przegladarek, ktore krok URL moze otworzyc - do zamkniecia okna po
# potwierdzeniu (zamykamy TYLKO okno otwarte przez ten skrypt, patrz Close-NewWindows).
$browsers = @("chrome", "msedge", "firefox", "brave", "opera", "iexplore")

# Kazda pozycja: nazwa, instrukcja, cel do otwarcia (Url / App / Terminal) oraz
# Proc = nazwy procesow, ktorych NOWE okno zamykamy po potwierdzeniu (redukcja
# liczby okienek - user prosil, zeby skrypt sprzatal po sobie).
$logins = @(
    @{ Key = "claude_code";   Name = "Claude Code (CLI)";
       Info = "Otwieram terminal z poleceniem `claude` - zaloguj sie na subskrypcje. To naped glownego modelu agenta.";
       Terminal = "claude"; Proc = @("WindowsTerminal", "powershell", "pwsh") }
    @{ Key = "vscode_cloud";  Name = "VS Code - konto CHMUROWE (firmowe)";
       Info = "Otworz VS Code, LEWY dolny rog (ikona konta) -> Sign in. Zaloguj konto firmowe (Microsoft 365).";
       App = "code"; Proc = @("Code") }
    @{ Key = "vscode_personal"; Name = "VS Code - konto PERSONALNE";
       Info = "W VS Code dodaj drugie konto: LEWY dolny rog (ikona konta) -> Sign in - personalne, do Settings Sync / GitHub.";
       App = "code"; Proc = @("Code") }
    @{ Key = "microsoft365";  Name = "Microsoft 365 (chmura) w przegladarce";
       Info = "Zaloguj konto firmowe - mail, SharePoint, OneDrive. Czesc pracy idzie przez interfejs, nie tylko API.";
       Url = "https://www.office.com/"; Proc = $browsers }
    @{ Key = "office_activate"; Name = "Office (Excel/Word) - AKTYWACJA licencji";
       Info = "Otworz Excela lub Worda, zaloguj sie kontem Microsoft 365 Business Standard - to aktywuje pakiet. Instalacja dziala bez logowania, ale bez aktywacji Office chodzi w trybie ograniczonym.";
       App = "excel"; Proc = @("EXCEL") }
    @{ Key = "gmail";         Name = "Gmail / Google (przegladarka)";
       Info = "Zaloguj konto Google. Potrzebne, bo nie wszystko robimy przez API - czasem trzeba przez interfejs.";
       Url = "https://accounts.google.com/"; Proc = $browsers }
    @{ Key = "meta_business"; Name = "Meta Business (przegladarka)";
       Info = "Zaloguj Business Manager - kampanie i zmiany, ktore robimy przez interfejs Meta.";
       Url = "https://business.facebook.com/"; Proc = $browsers }
    @{ Key = "github";        Name = "GitHub (repozytoria stron)";
       Info = "Zaloguj GitHub w przegladarce i/lub w VS Code - repozytoria stron internetowych.";
       Url = "https://github.com/login"; Proc = $browsers }
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

function Open-Terminal($command) {
    # Otwiera NOWE okno terminala i uruchamia w nim polecenie, zostawiajac je
    # otwarte (uzytkownik loguje sie interaktywnie, np. `claude`). Preferuje
    # Windows Terminal (wt); gdy go nie ma - zwykly PowerShell.
    if (Get-Command wt -ErrorAction SilentlyContinue) {
        Start-Process "wt" -ArgumentList "powershell -NoExit -Command $command"
    } else {
        Start-Process "powershell" -ArgumentList "-NoExit", "-Command", $command
    }
}

function Get-WindowPids($names) {
    # Id procesow o podanych nazwach - "zdjecie" PRZED otwarciem, zeby pozniej
    # rozpoznac, ktore okno otworzyl ten skrypt.
    if (-not $names) { return @() }
    @(Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $names -contains $_.Name } | Select-Object -ExpandProperty Id)
}

function Close-NewWindows($names, $beforePids) {
    # Zamyka TYLKO nowe okna top-level (MainWindowHandle != 0) procesow z `names`,
    # ktorych PID nie bylo w $beforePids - czyli te otwarte przez ten krok skryptu.
    # Nie rusza okien, ktore user mial otwarte wczesniej (np. wlasna przegladarka).
    if (-not $names) { return }
    $new = @(Get-Process -ErrorAction SilentlyContinue | Where-Object {
        ($names -contains $_.Name) -and ($beforePids -notcontains $_.Id) -and ($_.MainWindowHandle -ne 0)
    })
    if (-not $new) { return }
    foreach ($p in $new) { try { [void]$p.CloseMainWindow() } catch {} }
    Start-Sleep -Milliseconds 1200
    foreach ($p in $new) {
        try { $p.Refresh(); if (-not $p.HasExited) { $p.Kill() } } catch {}
    }
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
    # "Zdjecie" procesow PRZED otwarciem - po potwierdzeniu zamkniemy tylko to,
    # co ten krok otworzyl (zeby nie robilo sie wiele okienek naraz).
    $beforePids = Get-WindowPids $l.Proc
    if ($l.Terminal) {
        Write-Host ("    Otwieram terminal i uruchamiam: $($l.Terminal)")
        Open-Terminal $l.Terminal
    } elseif ($l.Url) {
        Write-Host ("    Otwieram: $($l.Url)")
        Start-Process $l.Url
    } elseif ($l.App) {
        if (Get-Command $l.App -ErrorAction SilentlyContinue) { Start-Process $l.App }
        else { Write-Host ("    (Aplikacja '$($l.App)' niedostepna w PATH - otworz recznie)") -ForegroundColor Yellow }
    }
    # Czekamy na JEDNOZNACZNA odpowiedz - dopiero wtedy przechodzimy dalej.
    # Przypadkowy Enter / bledny znak nie pomija kroku (pyta ponownie).
    $ans = ""
    while ($ans -notin @("t", "p", "q")) {
        $ans = (Read-Host "    Zalogowane? [t=tak / p=pomin / q=przerwij]").ToLower().Trim()
    }
    if ($ans -eq "q") { Write-Host "Przerwano."; break }
    if ($ans -eq "t") { $done += $l.Key; Write-Host "    OK" -ForegroundColor Green }
    else { Write-Host "    Pominieto" -ForegroundColor Yellow }
    # Zamknij okno otwarte przez ten krok, zanim przejdziemy do nastepnego.
    Close-NewWindows $l.Proc $beforePids
}

Save-Status $done
Write-Host "`nZapisano stan logowan: $statusPath"
Write-Host "Potwierdzone: $($done.Count)/$($logins.Count)"
exit 0
