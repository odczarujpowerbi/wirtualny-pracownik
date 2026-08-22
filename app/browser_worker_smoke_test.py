"""
Test dymny workera przeglądarkowego (browser_task, Playwright). CELOWO BEZ
REALNEJ PRZEGLĄDARKI — strona jest atrapą (_FakePage), wstrzykiwaną przez
_page_factory, dokładnie tak jak `opener` we web_fetch_worker_smoke_test.py.
Dzięki temu test jest szybki, deterministyczny i nie wymaga zainstalowanego
Playwright/Chromium na maszynie, na której akurat leci self_check.

Pokrywa: happy path (kilka kroków), odmowy bezpieczeństwa (host spoza
allowlisty, nie-https, krok 'goto' poza allowlistą w trakcie sekwencji),
walidację kroków PRZED odpaleniem przeglądarki, przerwanie sekwencji na
błędzie pojedynczego kroku (ze zrzutem stanu awarii) oraz egzekwowanie
kontraktu w tool_registry i wpięcie w executor.

Użycie:
    python browser_worker_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import browser_worker
import executor
import risk_hint
import tool_registry

ALLOWED = ["przyklad.example"]


class _FakePage:
    """Atrapa strony Playwright — bez sieci, bez realnej przeglądarki."""

    def __init__(self, fail_on=None):
        self.url = "https://przyklad.example/start"
        self._title = "Strona testowa"
        self.actions = []
        self.fail_on = fail_on  # nazwa akcji, na której ma rzucić wyjątek

    def goto(self, url, timeout=None):
        self.actions.append(("goto", url))
        if self.fail_on == "goto" and url != "https://przyklad.example/start":
            raise RuntimeError("nawigacja nie powiodła się")
        self.url = url

    def click(self, selector, timeout=None):
        self.actions.append(("click", selector))
        if self.fail_on == "click":
            raise RuntimeError("element nie znaleziony")

    def fill(self, selector, text, timeout=None):
        self.actions.append(("fill", selector, text))
        if self.fail_on == "fill":
            raise RuntimeError("pole nie znalezione")

    def wait_for_selector(self, selector, timeout=None):
        self.actions.append(("wait_for_selector", selector))
        if self.fail_on == "wait_for_selector":
            raise RuntimeError("selektor nie pojawił się")

    def screenshot(self, path=None, full_page=True):
        Path(path).write_bytes(b"\x89PNG_fake")

    def title(self):
        return self._title

    def inner_text(self, selector):
        return "Nagłówek strony testowej.\nTreść widoczna dla użytkownika."


def _factory(fail_on=None):
    page = _FakePage(fail_on=fail_on)
    return lambda: (page, lambda: None)


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    with tempfile.TemporaryDirectory() as tmp:
        # --- happy path: kilka kroków ---
        kroki = [
            {"action": "click", "selector": "#zgoda"},
            {"action": "fill", "selector": "#email", "text": "test@example.com"},
            {"action": "wait_for_selector", "selector": "#potwierdzenie"},
        ]
        res = browser_worker.run("https://przyklad.example/start", steps=kroki, allowed_hosts=ALLOWED,
                                 out_dir=tmp, _page_factory=_factory())
        checks.append(("Happy path: available=True", res["available"] is True))
        checks.append(("Happy path: wykonano wszystkie kroki", res["steps_done"] == res["steps_total"] == 3))
        checks.append(("Happy path: zrzut zapisany na dysku",
                       res["screenshot_path"] and Path(res["screenshot_path"]).exists()))
        checks.append(("Happy path: tytuł strony w wyniku", res["title"] == "Strona testowa"))
        checks.append(("Happy path: tekst strony wyciągnięty (page_text)",
                       "Treść widoczna dla użytkownika" in res.get("page_text", "")))

        # --- odmowy bezpieczeństwa (przed odpaleniem jakiejkolwiek strony) ---
        obcy = browser_worker.run("https://zlosliwa-domena.example/x", allowed_hosts=ALLOWED,
                                  out_dir=tmp, _page_factory=_factory())
        checks.append(("Host spoza allowlisty -> odmowa bez otwierania strony",
                       obcy["available"] is False and "allowlistą" in obcy["detail"]))

        plain = browser_worker.run("http://przyklad.example/x", allowed_hosts=ALLOWED,
                                   out_dir=tmp, _page_factory=_factory())
        checks.append(("Adres http (bez TLS) -> odmowa", plain["available"] is False and "https" in plain["detail"]))

        pusta = browser_worker.run("https://przyklad.example/x", allowed_hosts=[],
                                   out_dir=tmp, _page_factory=_factory())
        checks.append(("Pusta allowlista -> odmowa (fail-closed)", pusta["available"] is False))

        # --- walidacja kroków PRZED odpaleniem przeglądarki ---
        zly_krok = browser_worker.run("https://przyklad.example/start",
                                      steps=[{"action": "eval", "code": "alert(1)"}],
                                      allowed_hosts=ALLOWED, out_dir=tmp, _page_factory=_factory())
        checks.append(("Nieznana akcja kroku -> odmowa, przeglądarka NIE odpalona",
                       zly_krok["available"] is False and "nieznana" in zly_krok["detail"]))

        brak_selektora = browser_worker.run("https://przyklad.example/start",
                                            steps=[{"action": "click"}],
                                            allowed_hosts=ALLOWED, out_dir=tmp, _page_factory=_factory())
        checks.append(("Brak wymaganego pola 'selector' -> odmowa",
                       brak_selektora["available"] is False and "selector" in brak_selektora["detail"]))

        # --- 'goto' w trakcie sekwencji poza allowlistą -> przerwanie, ze zrzutem stanu ---
        wyjscie = browser_worker.run(
            "https://przyklad.example/start",
            steps=[{"action": "click", "selector": "#link"}, {"action": "goto", "url": "https://inna.example/x"}],
            allowed_hosts=ALLOWED, out_dir=tmp, _page_factory=_factory())
        checks.append(("Krok 'goto' poza allowlistą -> przerwanie sekwencji",
                       wyjscie["available"] is False and wyjscie["steps_done"] == 1))
        checks.append(("Przerwana sekwencja i tak ma zrzut stanu (diagnoza)",
                       wyjscie["screenshot_path"] and Path(wyjscie["screenshot_path"]).exists()))

        # --- błąd pojedynczego kroku przerywa resztę, ze zrzutem stanu awarii ---
        awaria = browser_worker.run(
            "https://przyklad.example/start",
            steps=[{"action": "click", "selector": "#a"}, {"action": "fill", "selector": "#b", "text": "x"},
                   {"action": "click", "selector": "#c"}],
            allowed_hosts=ALLOWED, out_dir=tmp, _page_factory=_factory(fail_on="fill"))
        checks.append(("Błąd kroku 2/3 -> przerwanie, steps_done=1 (krok 3 NIE wykonany)",
                       awaria["available"] is False and awaria["steps_done"] == 1))
        checks.append(("Powód błędu wskazuje numer i typ kroku", "Krok 2 (fill)" in awaria["detail"]))

        # --- profil logowania: niezalogowany -> odmowa BEZ próby odpalenia przeglądarki ---
        niezalogowany = browser_worker.run("https://przyklad.example/start", allowed_hosts=ALLOWED,
                                           out_dir=tmp, profile="nieistniejacy_profil_xyz")
        checks.append(("Profil niezalogowany -> odmowa z instrukcją --login",
                       niezalogowany["available"] is False and "--login" in niezalogowany["detail"]))

        # --- profil logowania: zalogowany (atrapa) -> używa _persistent_page_factory ---
        zalogowany_dir = Path(tmp) / "profil_test"
        zalogowany_dir.mkdir()
        original_profiles_dir, original_persistent = browser_worker.PROFILES_DIR, browser_worker._persistent_page_factory
        try:
            browser_worker.PROFILES_DIR = Path(tmp)
            wolania = []
            browser_worker._persistent_page_factory = lambda profile, headless=True: (
                wolania.append((profile, headless)) or _factory()())
            res_profil = browser_worker.run("https://przyklad.example/start", allowed_hosts=ALLOWED,
                                            out_dir=tmp, profile="profil_test")
            checks.append(("Profil zalogowany -> wykonuje zadanie przez trwały kontekst",
                           res_profil["available"] is True and wolania == [("profil_test", True)]))
        finally:
            browser_worker.PROFILES_DIR, browser_worker._persistent_page_factory = original_profiles_dir, original_persistent

    # --- kontrakt narzędzia (tool_registry) ---
    dozwolony = tool_registry.check_call("browser_task", {"url": "https://dashboard.mailerlite.com/dashboard"})
    checks.append(("Kontrakt: domena z allowlisty (MailerLite) przechodzi",
                   dozwolony["allowed"] is True and dozwolony["risk"] == "yellow"))

    spoza_listy = tool_registry.check_call("browser_task", {"url": "https://cokolwiek.example/x"})
    checks.append(("Kontrakt: host spoza allowed_domains -> odmowa (fail-closed)",
                   spoza_listy["allowed"] is False and "allowed_domains" in spoza_listy["reason"]))

    brak_url = tool_registry.check_call("browser_task", {})
    checks.append(("Kontrakt: brak adresu -> odmowa", brak_url["allowed"] is False))

    # --- wpięcie w executor (bez sieci: kontrakt odmawia, zanim browser_worker w ogóle ruszy) ---
    odmowa = executor.execute({"action": "browser_task", "url": "https://cokolwiek.example/x"})
    checks.append(("Executor: host spoza allowlisty -> executed=False (fail-closed)",
                   odmowa is not None and odmowa["executed"] is False and odmowa["tool"] == "browser_task"))

    odmowa_profilu = executor.execute({"action": "browser_task", "url": "https://dashboard.mailerlite.com/x",
                                       "browser_profile": "nieznany_profil"})
    checks.append(("Executor: nieznany profil (spoza allowed_profiles) -> executed=False",
                   odmowa_profilu is not None and odmowa_profilu["executed"] is False
                   and "allowed_profiles" in odmowa_profilu["acceptance_notes"]))

    nieznane = executor.execute({"action": "cos_czego_nie_ma"})
    checks.append(("Executor: nieobsługiwana akcja -> None (nic nie udaje)", nieznane is None))

    # --- routing po domenie: zadania z Projectly nie mają pola 'action' ani 'url',
    # więc adres wyłuskany z treści musi jednoznacznie trafić do właściwego narzędzia ---
    z_tresci_browser = executor.rozpoznaj_narzedzie(
        {"title": "Sprawdź kampanie", "description": "Zobacz https://dashboard.mailerlite.com/dashboard"})
    checks.append(("Adres MailerLite w treści (bez action, bez kroków) -> browser_task_readonly",
                   z_tresci_browser == "browser_task_readonly"))

    z_tresci_fetch = executor.rozpoznaj_narzedzie(
        {"title": "Podaj kurs EUR", "description": "https://api.nbp.pl/api/exchangerates/rates/a/eur/"})
    checks.append(("Adres NBP w treści -> nadal rozpoznany jako fetch_url (brak konfliktu domen)",
                   z_tresci_fetch == "fetch_url"))

    z_krokami = executor.rozpoznaj_narzedzie(
        {"title": "Kliknij coś na kampanii", "description": "https://dashboard.mailerlite.com/dashboard",
         "browser_steps": [{"action": "click", "selector": "#a"}]})
    checks.append(("Adres MailerLite Z krokami klikania -> zwykłe browser_task (nie readonly)",
                   z_krokami == "browser_task"))

    hint_readonly = risk_hint.hint_from_task(
        {"title": "Sprawdź wyniki kampanii reklamowej"}, tool="browser_task_readonly")
    checks.append(("Słowo 'kampania' + browser_task_readonly -> mimo to 'green' (bez kroków klikania)",
                   hint_readonly == "green"))

    hint_z_krokami = risk_hint.hint_from_task(
        {"title": "Sprawdź wyniki kampanii reklamowej"}, tool="browser_task")
    checks.append(("Słowo 'kampania' + browser_task (Z krokami) -> nadal 'red' (realne klikanie)",
                   hint_z_krokami == "red"))

    profil_z_domeny = executor._profile_for_url(
        "https://dashboard.mailerlite.com/x", tool_registry.get_contract("browser_task"))
    checks.append(("Auto-dobór profilu po domenie MailerLite -> 'mailerlite'",
                   profil_z_domeny == "mailerlite"))

    profil_meta = executor._profile_for_url(
        "https://business.facebook.com/adsmanager", tool_registry.get_contract("browser_task"))
    checks.append(("Auto-dobór profilu po domenie Meta -> 'meta_ads'", profil_meta == "meta_ads"))

    profil_gov = executor._profile_for_url(
        "https://www.podatki.gov.pl/x", tool_registry.get_contract("browser_task"))
    checks.append(("Domena bez logowania (gov.pl) -> brak profilu (None)", profil_gov is None))

    # --- wpięcie w executor: happy path z podmienionym kontraktem i browser_worker.run ---
    original_get_contract, original_run = tool_registry.get_contract, browser_worker.run
    original_answer = executor.web_answer.answer
    try:
        with tempfile.TemporaryDirectory() as tmp:
            shot = Path(tmp) / "efekt.png"
            shot.write_bytes(b"\x89PNG_fake")

            tool_registry.get_contract = lambda tool, path=tool_registry.CONTRACTS_PATH: (
                {"risk": "yellow", "allowed_domains": ["przyklad.example"], "params": {"url": {"required": True, "type": "url"}}}
                if tool == "browser_task" else original_get_contract(tool, path))
            browser_worker.run = lambda url, steps=None, allowed_hosts=(), **kw: {
                "available": True, "url": url, "final_url": url, "title": "Strona testowa",
                "screenshot_path": str(shot), "steps_done": len(steps or []), "steps_total": len(steps or []),
                "page_text": "Sekcje menu: Cennik, Kontakt, O nas.", "detail": "OK"}
            executor.web_answer.answer = lambda question, content, url="", zrodlo_opis=None, ask=None: {
                "available": True, "answer": "Menu zawiera: Cennik, Kontakt, O nas.",
                "cost_usd": 0.002, "source": "atrapa", "detail": "OK"}

            wynik = executor.execute({"action": "browser_task", "url": "https://przyklad.example/x",
                                      "title": "Jakie sekcje ma menu?",
                                      "browser_steps": [{"action": "click", "selector": "#a"}]})
            checks.append(("Executor: dozwolony host -> zadanie wykonane",
                           wynik is not None and wynik["executed"] is True))
            checks.append(("Executor: acceptance_notes to REALNA odpowiedź modelu, nie log techniczny",
                           wynik["acceptance_notes"] == "Menu zawiera: Cennik, Kontakt, O nas."))
            checks.append(("Executor: koszt wywołania modelu raportowany", wynik["cost_usd"] == 0.002))
            checks.append(("Executor: screenshot_path w wyniku", wynik["screenshot_path"] == str(shot)))
            checks.append(("Executor: functional_check nonempty_file na zrzucie",
                           any(c["type"] == "nonempty_file" for c in wynik.get("functional_checks", []))))
            checks.append(("Executor: BRAK 'rerun' (kroki mogą mieć efekty uboczne)",
                           "rerun" not in wynik))

            # --- brak page_text (np. pusta strona) -> jawna informacja, nie udajemy materiału ---
            browser_worker.run = lambda url, steps=None, allowed_hosts=(), **kw: {
                "available": True, "url": url, "final_url": url, "title": "Pusta strona",
                "screenshot_path": str(shot), "steps_done": 0, "steps_total": 0,
                "page_text": "", "detail": "OK"}
            bez_tekstu = executor.execute({"action": "browser_task", "url": "https://przyklad.example/x"})
            checks.append(("Executor: brak page_text -> jawne 'UWAGA', nie udawany materiał",
                           bez_tekstu["executed"] is True and "UWAGA" in bez_tekstu["acceptance_notes"]))
    finally:
        tool_registry.get_contract, browser_worker.run = original_get_contract, original_run
        executor.web_answer.answer = original_answer

    print("\n--- Wynik testu dymnego browser_worker ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
