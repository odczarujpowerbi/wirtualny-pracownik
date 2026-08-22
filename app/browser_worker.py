"""
Worker przeglądarkowy (Playwright) — zadania webowe wymagające KLIKANIA, nie
tylko odczytu (nawigacja po stronie renderowanej JS-em, wypełnienie formularza,
zrzut po interakcji). Tam, gdzie web_fetch_worker.py wystarcza (czyste HTTPS
GET), zostaje web_fetch_worker — ten moduł jest dla zadań, których fetch_url
nie umie wykonać.

Fail-closed jak reszta warstwy sieciowej (web_fetch_worker.py): TYLKO https,
TYLKO hosty z allowlisty kontraktu (`browser_task` w config/tool_contracts.yaml),
każda nawigacja — początkowa i każdy kolejny krok 'goto' — sprawdzana ponownie
wobec allowlisty. Zestaw kroków jest ZAMKNIĘTY i deklaratywny (goto/click/fill/
wait_for_selector/screenshot) — model nie dostaje dowolnego JS ani polecenia
powłoki, tylko te pięć czasowników. Błąd pojedynczego kroku przerywa resztę
sekwencji (nie próbujemy zgadywać dalej) i zwraca zrzut stanu w momencie awarii
do diagnozy.

Degradacja: brak zainstalowanego Playwright/Chromium -> available=False z
czytelnym powodem (pip install playwright && playwright install chromium),
nigdy wyjątek — ten sam wzorzec co screenshot_capture.py/ui_actions.py dla
brakujących backendów.

Sesje logowania (profile): część stron (panel MailerLite, Meta Ads Manager)
wymaga zalogowania. `run(..., profile="nazwa")` używa TRWAŁEGO profilu
przeglądarki zapisanego w secrets/browser_profiles/<profil> (nigdy w repo —
to odpowiednik poświadczenia). Profil trzeba najpierw zalogować RĘCZNIE,
jednorazowo: `python browser_worker.py --login <profil> <adres_logowania>`
(otwiera prawdziwe okno przeglądarki, człowiek loguje się sam — agent nigdy
nie wpisuje danych logowania). Dozwolone nazwy profili i domeny per profil
pilnuje `executor.py` przez `config/tool_contracts.yaml`.

Użycie:
    python browser_worker.py https://przyklad.example przyklad.example
    python browser_worker.py --login mailerlite https://dashboard.mailerlite.com/dashboard
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from web_fetch_worker import host_allowed

OUT_DIR = Path(__file__).parent / "runs" / "browser"
PROFILES_DIR = Path(__file__).parent / "secrets" / "browser_profiles"
DEFAULT_TIMEOUT_MS = 15_000
_ALLOWED_STEP_ACTIONS = {"goto", "click", "fill", "wait_for_selector", "screenshot"}


def available():
    try:
        import playwright.sync_api  # noqa: F401
    except ImportError:
        return False
    return True


def _shot_name():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"shot_{stamp}.png"


def _unavailable(detail, url=None):
    return {"available": False, "url": url, "final_url": None, "title": None,
            "screenshot_path": None, "steps_done": 0, "steps_total": 0, "detail": detail}


def _validate_steps(steps):
    """Sprawdza kroki PRZED odpaleniem przeglądarki — zły krok nie ma otwierać
    okna, żeby potem i tak nic nie zrobić."""
    for i, step in enumerate(steps):
        action = (step or {}).get("action")
        if action not in _ALLOWED_STEP_ACTIONS:
            return f"Krok {i + 1}: akcja '{action}' nieznana (dozwolone: {sorted(_ALLOWED_STEP_ACTIONS)})."
        if action in ("click", "fill", "wait_for_selector") and not step.get("selector"):
            return f"Krok {i + 1} ({action}): brak wymaganego pola 'selector'."
        if action == "fill" and not step.get("text"):
            return f"Krok {i + 1} (fill): brak wymaganego pola 'text'."
        if action == "goto" and not step.get("url"):
            return f"Krok {i + 1} (goto): brak wymaganego pola 'url'."
    return None


def _real_page_factory():
    """Prawdziwa przeglądarka (Chromium headless, BEZ zapisanej sesji — czysty
    profil za każdym razem). Zwraca (page, close)."""
    from playwright.sync_api import sync_playwright  # lazy: opcjonalna zależność

    ctx = sync_playwright().start()
    browser = ctx.chromium.launch(headless=True)
    page = browser.new_page()

    def _close():
        try:
            browser.close()
        finally:
            ctx.stop()

    return page, _close


def _profile_dir(profile):
    return PROFILES_DIR / profile


def _persistent_page_factory(profile, headless=True):
    """Przeglądarka z TRWAŁYM profilem (ciasteczka/sesja logowania zapisane na
    dysku w secrets/browser_profiles/<profile> — NIGDY w repo, to odpowiednik
    poświadczenia). Do zadań wymagających zalogowanej sesji (np. panel
    MailerLite, Meta Ads Manager), której zwykły `_real_page_factory` nie ma.

    Profil trzeba najpierw ZALOGOWAĆ RĘCZNIE (funkcja `login()` poniżej,
    niegłoheadless) — sam browser_worker nigdy nie wpisuje danych logowania."""
    from playwright.sync_api import sync_playwright  # lazy: opcjonalna zależność

    ctx = sync_playwright().start()
    context = ctx.chromium.launch_persistent_context(str(_profile_dir(profile)), headless=headless)
    page = context.pages[0] if context.pages else context.new_page()

    def _close():
        try:
            context.close()
        finally:
            ctx.stop()

    return page, _close


def login(profile, url, out=print):
    """Otwiera profil NIEGŁOHEADLESS na `url`, żeby CZŁOWIEK zalogował się
    ręcznie — jednorazowo, przed pierwszym użyciem `run(..., profile=...)`.
    Agent NIGDY nie wpisuje tu danych logowania (login/hasło/2FA to sprawa
    człowieka). Sesja zapisuje się do secrets/browser_profiles/<profile> przy
    zamknięciu kontekstu.

    Wymaga prawdziwego ekranu (RDP na maszynie) — okno przeglądarki się otwiera
    naprawdę. Zamknij je (albo wciśnij Enter w konsoli), żeby zapisać sesję."""
    if not available():
        out("Playwright niedostępny (pip install playwright && playwright install chromium).")
        return False

    from playwright.sync_api import sync_playwright

    profile_dir = _profile_dir(profile)
    profile_dir.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(profile_dir), headless=False)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url)
        out(f"Zaloguj się ręcznie w otwartym oknie przeglądarki (profil '{profile}').")
        out("Po zalogowaniu zamknij okno przeglądarki albo wciśnij Enter tutaj, żeby zapisać sesję.")
        try:
            input()
        except EOFError:
            pass
        context.close()
    out(f"Sesja zapisana: {profile_dir}")
    return True


def run(url, steps=None, allowed_hosts=(), timeout_ms=DEFAULT_TIMEOUT_MS, out_dir=None,
        profile=None, _page_factory=None):
    """Otwiera `url` w przeglądarce i wykonuje `steps` po kolei. Nigdy nie rzuca —
    zwraca zawsze dict: {available, url, final_url, title, screenshot_path,
    steps_done, steps_total, detail}.

    allowed_hosts: allowlista hostów z kontraktu narzędzia (jak przy fetch_url),
    sprawdzana dla adresu startowego I dla każdego kroku 'goto'. Pusta = odmowa.
    profile: nazwa TRWAŁEGO profilu (secrets/browser_profiles/<profile>) do
    zadań wymagających zalogowanej sesji — musi być wcześniej zalogowany
    funkcją `login()`. Bez tego (domyślnie None) — świeża, niezalogowana
    przeglądarka, jak dotąd.
    _page_factory: wstrzykiwane w testach (atrapa strony — bez realnego Playwright,
    tak jak `opener` we web_fetch_worker.fetch)."""
    steps = steps or []
    if urlparse(url or "").scheme != "https":
        return _unavailable("Dozwolone są tylko adresy https (fail-closed).", url)
    if not host_allowed(url, allowed_hosts):
        return _unavailable(
            f"Host '{urlparse(url).hostname}' jest poza allowlistą {list(allowed_hosts)} — odmowa.", url)

    blad = _validate_steps(steps)
    if blad:
        return _unavailable(blad, url)

    if _page_factory is None:
        if not available():
            return _unavailable(
                "Playwright niedostępny (pip install playwright && playwright install chromium).", url)
        if profile:
            if not _profile_dir(profile).exists():
                return _unavailable(
                    f"Profil '{profile}' nie jest jeszcze zalogowany — uruchom najpierw "
                    f"`python browser_worker.py --login {profile} <adres_logowania>` ręcznie na maszynie.", url)
            _page_factory = lambda: _persistent_page_factory(profile, headless=True)  # noqa: E731
        else:
            _page_factory = _real_page_factory

    out_path = Path(out_dir) if out_dir else OUT_DIR
    out_path.mkdir(parents=True, exist_ok=True)
    shot_path = out_path / _shot_name()

    steps_done = 0
    blad_kroku = None
    final_url, title = url, None
    try:
        page, close = _page_factory()
        try:
            page.goto(url, timeout=timeout_ms)
            for step in steps:
                action = step["action"]
                try:
                    if action == "goto":
                        cel = step["url"]
                        if not host_allowed(cel, allowed_hosts):
                            blad_kroku = f"Krok goto na '{cel}' poza allowlistą hostów."
                            break
                        page.goto(cel, timeout=timeout_ms)
                    elif action == "click":
                        page.click(step["selector"], timeout=timeout_ms)
                    elif action == "fill":
                        page.fill(step["selector"], step["text"], timeout=timeout_ms)
                    elif action == "wait_for_selector":
                        page.wait_for_selector(step["selector"], timeout=timeout_ms)
                    # "screenshot": bez osobnej akcji — zrzut końcowy powstaje zawsze niżej.
                except Exception as exc:  # noqa: BLE001 — krok padł, przerywamy resztę (fail-closed)
                    blad_kroku = f"Krok {steps_done + 1} ({action}) nie powiódł się: {exc}"
                    break
                steps_done += 1
            final_url, title = page.url, page.title()
            page.screenshot(path=str(shot_path), full_page=True)
        finally:
            close()
    except Exception as exc:  # noqa: BLE001 — awaria samej przeglądarki (start/zamknięcie)
        return {**_unavailable(f"Przeglądarka: {exc}", url), "steps_done": steps_done, "steps_total": len(steps)}

    if blad_kroku:
        return {**_unavailable(blad_kroku, url), "screenshot_path": str(shot_path),
                "steps_done": steps_done, "steps_total": len(steps), "final_url": final_url, "title": title}

    return {
        "available": True, "url": url, "final_url": final_url, "title": title,
        "screenshot_path": str(shot_path), "steps_done": steps_done, "steps_total": len(steps),
        "detail": f"Wykonano {steps_done}/{len(steps)} kroków, zrzut zapisany.",
    }


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--login":
        if len(sys.argv) < 4:
            print("Użycie: python browser_worker.py --login <profil> <https://adres_logowania>")
            return 1
        return 0 if login(sys.argv[2], sys.argv[3]) else 1

    if len(sys.argv) < 2:
        print("Użycie: python browser_worker.py <https://adres> [host1,host2]")
        print("        python browser_worker.py --login <profil> <https://adres_logowania>")
        return 1
    url = sys.argv[1]
    hosts = sys.argv[2].split(",") if len(sys.argv) > 2 else [urlparse(url).hostname]
    result = run(url, allowed_hosts=hosts)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
