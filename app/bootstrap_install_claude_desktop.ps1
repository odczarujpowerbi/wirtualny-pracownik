# Pobiera i uruchamia instalator Claude Desktop — aplikacja z zakładkami
# Chat/Cowork/Code, w tym możliwością uruchamiania sesji w chmurze
# ("Cloud", nie tylko lokalnie) i podłączania integracji (Connectors/MCP)
# przez okienko zamiast ręcznej edycji configu.
#
# To instalator GUI (typowy Setup.exe) — ten skrypt automatyzuje samo
# POBRANIE, ale dokończenie instalacji (parę kliknięć "Dalej") zostaje po
# Twojej stronie. Brak potwierdzonej w oficjalnej dokumentacji flagi cichej
# instalacji dla tego konkretnego instalatora — nie zgaduję jej na ślepo.
#
# Na Windows zakładka "Code" wymaga Gita — jeśli jeszcze go nie masz,
# uruchom najpierw .\bootstrap_install_git.ps1.
#
# NIEtestowane w tej sesji: samo pobranie — domena downloads.claude.ai
# jest zablokowana w sieci TEJ sesji budowy (potwierdzone: "gateway
# answered 403 to CONNECT, policy denial"), co jest ograniczeniem
# środowiska budowy, nie kodu. Prawdziwa maszyna z normalnym dostępem do
# internetu nie napotka tego blokera. Jeśli mimo to pobieranie zawiedzie,
# pobierz ręcznie: https://claude.ai/download
#
# Użycie (PowerShell):
#   .\bootstrap_install_claude_desktop.ps1

$ErrorActionPreference = "Stop"

$downloadUrl = "https://claude.ai/api/desktop/win32/x64/setup/latest/redirect"
$installerPath = Join-Path $env:TEMP "ClaudeDesktopSetup.exe"

Write-Host "Pobieram instalator Claude Desktop..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $installerPath
} catch {
    Write-Error "Pobieranie nie powiodło się: $_. Pobierz ręcznie z https://claude.ai/download i uruchom instalator."
    exit 1
}

Write-Host "Uruchamiam instalator — dokończ instalację w oknie, które się zaraz pojawi (Dalej -> Zainstaluj)." -ForegroundColor Cyan
Start-Process -FilePath $installerPath -Wait
Remove-Item $installerPath -ErrorAction SilentlyContinue

Write-Host "`nPo zainstalowaniu: uruchom Claude, zaloguj się, kliknij zakładkę 'Code'." -ForegroundColor Green
Write-Host "Tam, w oknie startu sesji, możesz wybrać środowisko 'Cloud' zamiast 'Local' — sesja działa dalej nawet po zamknięciu aplikacji."
