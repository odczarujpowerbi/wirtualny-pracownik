#!/usr/bin/env bash
# Bootstrap dla testowego VPS-a z Linuksem (Ubuntu/Debian) — odpowiednik
# bootstrap_install.ps1, ale dla Linuksa zamiast Windows (SKALOWANIE.md
# sekcja 4). W przeciwieństwie do wersji Windows TEN skrypt był realnie
# uruchomiony i przetestowany end-to-end w tej sesji (środowisko budowy
# to Linux) — patrz WDROZENIE-VPS-TESTOWE.md.
#
# CZEGO TEN VPS NIE ZROBI: kroków wymagających Power BI Desktop (zrzuty
# realnego raportu, PBI-01/02) — to jedyny blocker Windows-specyficzny w
# całym repo (patrz app/README.md). Reszta (runner, digest, feedback,
# raporty, watcher danych, mail w trybie mock) działa identycznie.
#
# Użycie (adres repo opcjonalny — domyślnie repo projektu):
#   ./bootstrap_install_vps.sh [adres-repo-git] [ścieżka-instalacji]
# Przykład:
#   ./bootstrap_install_vps.sh
#   ./bootstrap_install_vps.sh https://github.com/odczarujpowerbi/wirtualny-pracownik.git ~/AIWorker

set -euo pipefail

# Repo projektu — jedno miejsce do zmiany (zgodne z config/repo.yaml; ten skrypt
# działa przed klonem, więc nie może wczytać tamtego pliku).
REPO_URL="${1:-https://github.com/odczarujpowerbi/wirtualny-pracownik.git}"
REPO_BRANCH="main"
INSTALL_PATH="${2:-$HOME/AIWorker}"

echo "=== 1. Sprawdzenie zależności systemowych ==="
for cmd in git python3; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
        echo "BŁĄD: '$cmd' nie jest zainstalowany. Na Ubuntu/Debian: sudo apt update && sudo apt install -y git python3 python3-venv python3-pip"
        exit 1
    fi
done
echo "git i python3 znalezione: $(git --version), $(python3 --version)"

echo "=== 2. Klonowanie repozytorium ==="
# Repo ma kod w korzeniu — klonujemy do podfolderu wirtualny-pracownik/, żeby
# lokalny układ to nadal $INSTALL_PATH/wirtualny-pracownik/app.
REPO_DIR="$INSTALL_PATH/wirtualny-pracownik"
if [ -d "$REPO_DIR/.git" ]; then
    # Repo już jest — ZAWSZE nadpisujemy kod do origin/$REPO_BRANCH. reset --hard
    # rusza tylko pliki wersjonowane, wiec secrets/ i runs/ (w .gitignore) zostaja.
    echo "$REPO_DIR już istnieje — nadpisuję kod do origin/$REPO_BRANCH (secrets/ i runs/ zostają)."
    git -C "$REPO_DIR" remote set-url origin "$REPO_URL"
    git -C "$REPO_DIR" fetch origin "$REPO_BRANCH"
    git -C "$REPO_DIR" reset --hard "origin/$REPO_BRANCH"
else
    if [ -d "$REPO_DIR" ]; then
        echo "$REPO_DIR istnieje, ale to nie repozytorium git — usuwam i klonuję świeżo."
        rm -rf "$REPO_DIR"
    fi
    mkdir -p "$INSTALL_PATH"
    git clone --branch "$REPO_BRANCH" "$REPO_URL" "$REPO_DIR"
fi

APP_PATH="$REPO_DIR/app"
if [ ! -d "$APP_PATH" ]; then
    echo "BŁĄD: nie znaleziono $APP_PATH — sprawdź czy podałeś właściwy adres repozytorium (kod ma być w korzeniu repo, w folderze app/)."
    exit 1
fi

echo "=== 3. Środowisko wirtualne i zależności Python ==="
cd "$APP_PATH"
python3 -m venv venv
# shellcheck disable=SC1091
source venv/bin/activate
pip install --upgrade pip >/dev/null
pip install -r requirements.txt

echo ""
echo "=== Gotowe ==="
echo "Dalsze kroki (WDROZENIE-VPS-TESTOWE.md):"
echo "  1. cd $APP_PATH"
echo "  2. cp .env.example .env && nano .env   # uzupełnij ANTHROPIC_API_KEY (Projectly gdy dostępne)"
echo "  3. source venv/bin/activate"
echo "  4. python bootstrap_smoke_test.py"
echo "  5. python bootstrap_register.py <rola>"
echo "  6. Uruchomienie cykliczne: cron albo systemd (patrz WDROZENIE-VPS-TESTOWE.md)"
