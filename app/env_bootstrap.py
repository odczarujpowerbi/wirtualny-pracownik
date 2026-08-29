"""
Ładuje zmienne środowiskowe z jednego, scentralizowanego miejsca —
`secrets/.env` (utworzone przez `bootstrap_init_secrets.py`) — zamiast
polegać na tym, że coś inne w tym samym procesie już to zrobiło wcześniej.

Importuj ten moduł (samym importem, bez wywołania funkcji) na górze
KAŻDEGO pliku, który czyta klucz API z `os.environ` — dzięki temu działa
też uruchomiony samodzielnie (`python jakiś_skrypt.py`), nie tylko przez
`runner_loop.py`. Podwójny import w tym samym procesie jest nieszkodliwy
(Python cache'uje moduły, `load_dotenv` samo w sobie też jest bezpieczne
do wielokrotnego wywołania).

Kolejność: najpierw zwykły `.env` w tym folderze (zgodność wstecz z
wcześniejszymi wdrożeniami/testami), potem `secrets/.env` z
`override=True` — nowe, scentralizowane miejsce zawsze wygrywa, jeśli
istnieje. Na końcu (też `override=True`, więc wygrywa nad wszystkim
powyższym) `secrets/agents/<rola>/.env` — sekrety WŁAŚCIWE DLA ROLI tej
maszyny (`config/role.json`), np. osobny token Projectly per bot-rola
(dev/marketing/...), gdy jedna maszyna/instancja repo ma obsługiwać
konkretną rolę spośród wielu. Brak takiego folderu = brak zmiany
zachowania (fail-soft, jak `_load_role()` w `projectly_client.py`).
"""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def _current_role(role_path=None):
    """Kopia logiki _load_role() z projectly_client.py — nie importujemy
    stamtąd, żeby uniknąć zależności cyklicznej (projectly_client importuje
    ten moduł, nie na odwrót). role_path wstrzykiwalny (testowalność).

    Zmienna środowiskowa BOT_ROLE ma pierwszeństwo nad config/role.json —
    dodane 29.08.2026, żeby kilka procesów job_scheduler.py na TEJ SAMEJ
    maszynie/repo (dev/checker/marketing) mogło działać pod różnymi rolami
    bez współdzielenia (i nadpisywania sobie) jednego pliku role.json.
    Uruchomienie bez BOT_ROLE zachowuje się dokładnie jak wcześniej (czyta
    role.json, domyślnie "dev")."""
    if os.environ.get("BOT_ROLE"):
        return os.environ["BOT_ROLE"]
    role_path = role_path or Path(__file__).parent / "config" / "role.json"
    if role_path.exists():
        try:
            return json.loads(role_path.read_text(encoding="utf-8")).get("role", "dev")
        except (ValueError, OSError):
            return "dev"
    return "dev"

# Konsola Windows domyślnie NIE jest UTF-8 (tu: cp1250) i wywala się na emoji
# w komentarzach/statusach (np. ✅ ✅ → UnicodeEncodeError, ubija runner).
# Ponieważ ten moduł importuje KAŻDY punkt wejścia, wymuszamy tu UTF-8 na
# stdout/stderr raz dla całego procesu. errors="replace" — nawet nietypowy
# znak nigdy nie ubije procesu autonomicznego. Ten sam wzorzec co w self_check.py.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass  # strumień przekierowany do StringIO/pliku — już radzi sobie z Unicode

load_dotenv()
load_dotenv(Path(__file__).parent / "secrets" / ".env", override=True)
load_dotenv(Path(__file__).parent / "secrets" / "agents" / _current_role() / ".env", override=True)
