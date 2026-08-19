# Instaluje dodatkowe aplikacje uzywane na maszynie agenta, przez winget.
# Lista sterowana danymi (jeden plik zamiast wielu prawie identycznych skryptow).
# winget jest idempotentny: jesli pakiet juz jest, zglasza to i nie duplikuje.
#
# Zestaw (ustalony z uzytkownikiem + to, co bylo na maszynie referencyjnej):
#   - Power BI Desktop  : rdzen pracy raportowej (PBIP/PBIR) tego projektu.
#   - Obsidian          : baza wiedzy/notatki.
#   - Microsoft Teams   : komunikacja.
#   - Outlook (nowy)    : poczta (klasyczny Outlook wchodzi tez z Office 365 Apps).
#   - Google Chrome     : praca przez przegladarke (logowania Meta/Gmail, automatyzacja).
#   - Terminal Windows  : terminal.
#
# Plik w ASCII (bez polskich znakow) - patrz app/README.md, uwaga o BOM w PS 5.1.
#
# Uzycie:  powershell -ExecutionPolicy Bypass -File bootstrap_install_apps.ps1
$ErrorActionPreference = "Continue"

$apps = @(
    @{ Name = "Power BI Desktop";  Id = "Microsoft.PowerBI" }
    @{ Name = "Obsidian";          Id = "Obsidian.Obsidian" }
    @{ Name = "Microsoft Teams";   Id = "Microsoft.Teams" }
    @{ Name = "Outlook (nowy)";    Id = "Microsoft.Outlook" }
    @{ Name = "Google Chrome";     Id = "Google.Chrome" }
    @{ Name = "Terminal Windows";  Id = "Microsoft.WindowsTerminal" }
)

Write-Host "=== Dodatkowe aplikacje (winget) ==="

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host "UWAGA: winget niedostepny - pomijam. Zainstaluj aplikacje recznie albo doinstaluj App Installer ze Sklepu."
    exit 1
}

$fail = 0
foreach ($app in $apps) {
    Write-Host "`n- $($app.Name) ($($app.Id))..."
    # winget install jest idempotentny: przy juz zainstalowanym pakiecie konczy
    # sie komunikatem "already installed" i kodem !=0 nie zawsze - dlatego nie
    # traktujemy niezerowego kodu jako twardego bledu, tylko ostrzegamy.
    winget install -e --id $app.Id --accept-source-agreements --accept-package-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  (winget zwrocil kod $LASTEXITCODE - zwykle 'juz zainstalowane' albo do sprawdzenia recznie)"
        $fail++
    } else {
        Write-Host "  OK"
    }
}

Write-Host "`nZakonczono aplikacje. Pozycji z ostrzezeniem: $fail/$($apps.Count) (czesto to po prostu 'juz jest')."
exit 0
