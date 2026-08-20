"""
Test dymny workera internetowego (fetch_url). CELOWO BEZ SIECI — cała warstwa
HTTP jest wstrzykiwana atrapą openera, żeby test był szybki, deterministyczny
i nadawał się do cyklicznego self_check (sieć w teście regresji = fałszywe
czerwone przy każdej awarii cudzego serwera).

Pokrywa: happy path (HTML i JSON), odmowy bezpieczeństwa (host spoza allowlisty,
nie-https, przekierowanie poza allowlistę), błędy sieci/HTTP oraz egzekwowanie
kontraktu w tool_registry i odmowę na poziomie executora.

Użycie:
    python web_fetch_worker_smoke_test.py
"""

import io
import sys
import tempfile
import urllib.error
from pathlib import Path

import executor
import tool_registry
import web_fetch_worker

ALLOWED = ["api.nbp.pl", "pl.wikipedia.org"]

HTML = """<html><head><title>Kurs euro</title></head>
<body><script>alert('nie chcemy tego w tekscie')</script>
<h1>Nagłówek strony</h1><p>Kurs EUR wynosi 4,3165 zł.</p></body></html>"""

JSON_BODY = '{"code":"EUR","rates":[{"mid":4.3165}]}'


class _FakeResponse(io.BytesIO):
    def __init__(self, body, status=200, content_type="text/html; charset=utf-8", url="https://api.nbp.pl/x"):
        super().__init__(body.encode("utf-8"))
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._url = url

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class _FakeOpener:
    """Atrapa openera: zwraca zadaną odpowiedź albo rzuca zadany wyjątek."""

    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.last_headers = None

    def open(self, request, timeout=None):
        self.last_headers = dict(request.headers)
        if self.error:
            raise self.error
        return self.response


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- happy path: HTML ---
    with tempfile.TemporaryDirectory() as tmp:
        web_fetch_worker.OUT_DIR = Path(tmp)
        opener = _FakeOpener(_FakeResponse(HTML))
        res = web_fetch_worker.fetch("https://api.nbp.pl/strona", allowed_hosts=ALLOWED, opener=opener)
        checks.append(("HTML: pobranie się udaje", res["available"] is True and res["status"] == 200))
        checks.append(("HTML: wyciąga tytuł strony", res["title"] == "Kurs euro"))
        checks.append(("HTML: tekst zawiera treść, a NIE kod ze <script>",
                       "Kurs EUR wynosi 4,3165" in res["text"] and "alert(" not in res["text"]))
        checks.append(("HTML: zapisuje treść na dysk (efekt do sprawdzenia)",
                       res["saved_path"] and Path(res["saved_path"]).read_text(encoding="utf-8").strip() != ""))
        checks.append(("Wysyła nagłówek User-Agent (bez niego np. Wikipedia zwraca 403)",
                       "wirtualny-pracownik" in (opener.last_headers.get("User-agent", "")
                                                 or opener.last_headers.get("User-Agent", ""))))

        # --- happy path: JSON ---
        res_json = web_fetch_worker.fetch(
            "https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json", allowed_hosts=ALLOWED,
            opener=_FakeOpener(_FakeResponse(JSON_BODY, content_type="application/json")))
        checks.append(("JSON: formatuje i zachowuje wartości", res_json["available"] and "4.3165" in res_json["text"]))

        # --- odmowy bezpieczeństwa ---
        obcy = web_fetch_worker.fetch("https://zlosliwa-domena.example/x", allowed_hosts=ALLOWED,
                                      opener=_FakeOpener(_FakeResponse(HTML)))
        checks.append(("Host spoza allowlisty -> odmowa bez pobierania",
                       obcy["available"] is False and "allowlist" in obcy["detail"]))

        plain = web_fetch_worker.fetch("http://api.nbp.pl/x", allowed_hosts=ALLOWED,
                                       opener=_FakeOpener(_FakeResponse(HTML)))
        checks.append(("Adres http (bez TLS) -> odmowa", plain["available"] is False and "https" in plain["detail"]))

        pusta = web_fetch_worker.fetch("https://api.nbp.pl/x", allowed_hosts=[],
                                       opener=_FakeOpener(_FakeResponse(HTML)))
        checks.append(("Pusta allowlista -> odmowa (fail-closed)", pusta["available"] is False))

        checks.append(("Sufiks nie oszukuje allowlisty (api.nbp.pl.zly.example)",
                       web_fetch_worker.host_allowed("https://api.nbp.pl.zly.example/x", ALLOWED) is False))
        checks.append(("Subdomena dozwolonego hosta przechodzi",
                       web_fetch_worker.host_allowed("https://sub.pl.wikipedia.org/x", ALLOWED) is True))

        # --- przekierowanie poza allowlistę ---
        handler = web_fetch_worker._GuardedRedirectHandler(ALLOWED)
        try:
            handler.redirect_request(None, None, 302, "Found", {}, "https://gdzie-indziej.example/x")
            redirect_blocked = False
        except urllib.error.HTTPError:
            redirect_blocked = True
        checks.append(("Przekierowanie na host spoza allowlisty -> zablokowane", redirect_blocked))

        # --- błędy sieci i HTTP ---
        http_err = web_fetch_worker.fetch(
            "https://pl.wikipedia.org/x", allowed_hosts=ALLOWED,
            opener=_FakeOpener(error=urllib.error.HTTPError("https://pl.wikipedia.org/x", 403,
                                                            "Forbidden", {}, None)))
        checks.append(("HTTP 403 -> available=False z czytelnym powodem, bez wyjątku",
                       http_err["available"] is False and "403" in http_err["detail"]))

        net_err = web_fetch_worker.fetch(
            "https://api.nbp.pl/x", allowed_hosts=ALLOWED,
            opener=_FakeOpener(error=urllib.error.URLError("brak połączenia")))
        checks.append(("Brak połączenia -> available=False, bez wyjątku",
                       net_err["available"] is False and "połączyć" in net_err["detail"]))

        # --- limit rozmiaru ---
        duzy = web_fetch_worker.fetch("https://api.nbp.pl/duze", allowed_hosts=ALLOWED, max_bytes=50,
                                      opener=_FakeOpener(_FakeResponse("x" * 500, content_type="text/plain")))
        checks.append(("Przekroczony limit rozmiaru -> treść przycięta i oznaczona",
                       duzy["available"] and duzy["truncated"] and duzy["bytes"] == 50))

    # --- kontrakt narzędzia (tool_registry) ---
    ok = tool_registry.check_call("fetch_url", {"url": "https://api.nbp.pl/api/exchangerates/rates/a/eur/"})
    checks.append(("Kontrakt: dozwolony host przechodzi", ok["allowed"] is True and ok["risk"] == "green"))

    zly = tool_registry.check_call("fetch_url", {"url": "https://przypadkowa-strona.example/dane"})
    checks.append(("Kontrakt: host spoza allowed_domains -> odmowa",
                   zly["allowed"] is False and "allowed_domains" in zly["reason"]))

    brak = tool_registry.check_call("fetch_url", {})
    checks.append(("Kontrakt: brak adresu -> odmowa", brak["allowed"] is False))

    # --- odmowa na poziomie executora (bez sieci: zły host nigdy nie dochodzi do pobrania) ---
    odmowa = executor.execute({"action": "fetch_url", "url": "https://przypadkowa-strona.example/dane"})
    checks.append(("Executor: zadanie ze złym hostem -> executed=False (fail-closed)",
                   odmowa is not None and odmowa["executed"] is False and odmowa["tool"] == "fetch_url"))

    nieznane = executor.execute({"action": "cos_czego_nie_ma"})
    checks.append(("Executor: nieobsługiwana akcja -> None (nic nie udaje)", nieznane is None))

    # --- REGRESJA: rerun musi mieć ten sam kształt co output ---
    # Bartek porównuje sygnatury output i rerun(). Gdy rerun zwracał pełny wynik
    # pobrania, a output tylko podzbiór pól, KAŻDE zadanie internetowe wyglądało na
    # niedeterministyczne i bramka je odrzucała (realnie napotkane na pierwszym
    # przebiegu na żywo). Ten test pilnuje, żeby to nie wróciło.
    original_fetch, original_answer = web_fetch_worker.fetch, executor.web_answer.answer
    try:
        with tempfile.TemporaryDirectory() as tmp:
            plik = Path(tmp) / "pobrane.txt"
            plik.write_text("tresc", encoding="utf-8")
            web_fetch_worker.fetch = lambda url, **kw: {
                "available": True, "url": url, "final_url": url, "status": 200,
                "content_type": "application/json", "title": "", "text": '{"mid": 4.3165}',
                "bytes": 15, "truncated": False, "saved_path": str(plik), "detail": "OK"}
            executor.web_answer.answer = lambda question, content, url="", ask=None: {
                "available": True, "answer": "Kurs EUR: 4,3165 zł.", "cost_usd": 0.001,
                "source": "atrapa", "detail": "OK"}

            wynik = executor.execute({"action": "fetch_url", "title": "Podaj kurs EUR",
                                      "url": "https://api.nbp.pl/api/exchangerates/rates/a/eur/"})
            checks.append(("Executor: dozwolony host -> zadanie wykonane",
                           wynik is not None and wynik["executed"] is True))
            checks.append(("Regresja: rerun() zwraca DOKŁADNIE ten sam kształt co output",
                           wynik["rerun"]() == wynik["output"]))
            checks.append(("Odpowiedź modelu jest efektem zadania (nie surowy JSON)",
                           wynik["acceptance_notes"].startswith("Kurs EUR: 4,3165")))
            checks.append(("Koszt wywołania modelu jest raportowany", wynik["cost_usd"] == 0.001))
            checks.append(("Efekt ma test funkcjonalny na zapisanym pliku",
                           wynik["functional_checks"][0]["type"] == "nonempty_file"))
    finally:
        web_fetch_worker.fetch, executor.web_answer.answer = original_fetch, original_answer

    print("\n--- Wynik testu dymnego web_fetch_worker ---")
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
