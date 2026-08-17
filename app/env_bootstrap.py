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
istnieje.
"""

from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(Path(__file__).parent / "secrets" / ".env", override=True)
