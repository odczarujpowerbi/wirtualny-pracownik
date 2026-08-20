"""
Worker pobierania informacji z internetu (read-only GET) — pierwsza zdolność
agenta sięgająca poza maszynę. Świadomie wąski zakres: TYLKO HTTPS, TYLKO GET,
tylko hosty z allowlisty kontraktu (`fetch_url` w config/tool_contracts.yaml),
z twardym limitem rozmiaru i czasu. Żadnego wykonywania JS, żadnych ciasteczek,
żadnego wysyłania danych na zewnątrz poza samym adresem.

Dlaczego biblioteka standardowa, a nie `requests` + `bs4`: zero nowych zależności
(stdlib + certifi, które i tak jest w środowisku), a przez to zero nowej
powierzchni ataku i zero problemów instalacyjnych na świeżej VM.

Dwie rzeczy ustalone empirycznie na tej maszynie i zaszyte tutaj, bo bez nich
pobieranie NIE działa:
  1. Python na Windows nie korzysta z magazynu CA systemu — bez `certifi` każde
     https kończy się CERTIFICATE_VERIFY_FAILED. Gdy certifi brak, degradujemy
     się jawnie (available=False z powodem), NIE wyłączamy weryfikacji.
  2. Wikipedia (i wiele innych) odrzuca zapytania bez nagłówka User-Agent (403),
     więc wysyłamy jawny, opisowy UA z kontaktem.

Bezpieczeństwo przekierowań: serwer może odesłać 302 na inny host, co ominęłoby
allowlistę sprawdzoną przed wywołaniem. Dlatego KAŻDE przekierowanie jest tu
sprawdzane ponownie wobec `allowed_hosts` (fail-closed, defense in depth).

Degradacja jest łagodna: brak sieci / 403 / timeout zwracają available=False
z czytelnym powodem, nigdy wyjątku — warstwa wywołująca decyduje, co dalej.

Użycie:
    python web_fetch_worker.py https://api.nbp.pl/api/exchangerates/rates/a/eur/?format=json
"""

import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)

APP_DIR = Path(__file__).parent
OUT_DIR = APP_DIR / "runs" / "web"
USER_AGENT = "wirtualny-pracownik/1.0 (agent firmowy; kontakt@clickless.pl)"
TIMEOUT_SECONDS = 15
MAX_BYTES = 1_500_000
MAX_TEXT_CHARS = 20_000


def _ssl_context():
    """Kontekst TLS z certyfikatami certifi. Bez certifi zwraca None, a wywołujący
    degraduje się z jasnym powodem — nigdy nie wyłączamy weryfikacji certyfikatu."""
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def host_allowed(url, allowed_hosts):
    """Czy host adresu mieści się w allowliście (dokładnie albo jako subdomena).
    Pusta allowlista = odmowa (fail-closed)."""
    host = (urlparse(url).hostname or "").lower()
    if not host or not allowed_hosts:
        return False
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed_hosts)


class _GuardedRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Podąża za przekierowaniem tylko wtedy, gdy cel też jest na allowliście."""

    def __init__(self, allowed_hosts):
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not host_allowed(newurl, self.allowed_hosts):
            raise urllib.error.HTTPError(
                newurl, code,
                f"Przekierowanie na '{newurl}' poza allowliste hostow - odmowa (fail-closed).",
                headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    """Minimalna ekstrakcja tekstu z HTML: pomija script/style/noscript, zbiera
    tytuł osobno. Nie udaje pełnego parsera treści — ma dać czytelny tekst do
    oceny przez człowieka i model."""

    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self.title += data.strip()
        elif data.strip():
            self.parts.append(data.strip())

    def text(self):
        return re.sub(r"\n{3,}", "\n\n", "\n".join(self.parts))


def _decode(raw, content_type):
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    for enc in ([match.group(1)] if match else []) + ["utf-8", "cp1250", "latin-1"]:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def _extract(body, content_type):
    """Zwraca (tytuł, tekst) zależnie od typu treści: JSON formatujemy, HTML
    czyścimy, resztę zostawiamy bez zmian."""
    lowered = (content_type or "").lower()
    if "json" in lowered:
        try:
            return "", json.dumps(json.loads(body), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return "", body
    if "html" in lowered or body.lstrip().startswith("<"):
        parser = _TextExtractor()
        parser.feed(body)
        return parser.title, parser.text()
    return "", body


def _save(url, text):
    """Zapisuje pobraną treść do runs/web/ — realny, sprawdzalny efekt zadania
    (Franek robi na nim nonempty_file, człowiek może po prostu zajrzeć)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    host = (urlparse(url).hostname or "strona").replace(".", "-")
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    path = OUT_DIR / f"{host}-{digest}.txt"
    path.write_text(f"# ŹRÓDŁO: {url}\n\n{text}", encoding="utf-8")
    return str(path)


def prefer_polish_variant(url):
    """Dokumentacja Microsoft Learn ma wersje jezykowe pod tym samym adresem
    (/en-us/ -> /pl-pl/). Do materialu po polsku odbior biznesowy sluszznie chce
    polskiego zrodla, wiec proponujemy wariant PL — wywolujacy sprawdza, czy
    istnieje, i wraca do oryginalu, gdy go nie ma."""
    if "learn.microsoft.com/en-us/" in (url or ""):
        return url.replace("/en-us/", "/pl-pl/")
    return None


def human_url(url):
    """Adres do POKAZANIA człowiekowi. Odbiór biznesowy słusznie zauważył, że
    link do API REST jest bezużyteczny dla odbiorcy raportu ("jak szef zapyta
    'pokaż, skąd to', nie mam co kliknąć") — dla znanych API tłumaczymy adres
    techniczny na normalny adres strony."""
    match = re.match(r"https://([a-z-]+)\.wikipedia\.org/api/rest_v1/page/summary/(.+)$", url or "")
    if match:
        return f"https://{match.group(1)}.wikipedia.org/wiki/{match.group(2)}"
    return url


def _unavailable(url, detail):
    return {"available": False, "url": url, "detail": detail,
            "status": None, "title": "", "text": "", "saved_path": None}


def fetch(url, allowed_hosts=(), timeout=TIMEOUT_SECONDS, max_bytes=MAX_BYTES, opener=None,
          try_polish=True):
    """Pobiera stronę/API i zwraca ustrukturyzowany wynik. Nigdy nie rzuca —
    problem sieci/HTTP wraca jako available=False z powodem.

    allowed_hosts: allowlista hostów (z kontraktu narzędzia), sprawdzana także
    dla każdego przekierowania. Pusta = odmowa.
    opener: wstrzykiwany na potrzeby testów (test dymny nie rusza sieci)."""
    parsed = urlparse(url or "")
    if parsed.scheme != "https":
        return _unavailable(url, "Dozwolone są tylko adresy https (fail-closed).")
    if not host_allowed(url, allowed_hosts):
        return _unavailable(url, f"Host '{parsed.hostname}' jest poza allowlistą {list(allowed_hosts)} — odmowa.")

    if opener is None:
        context = _ssl_context()
        if context is None:
            return _unavailable(url, "Brak pakietu 'certifi' — bez magazynu CA nie da się bezpiecznie "
                                     "zweryfikować certyfikatu (pip install certifi).")
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=context),
            _GuardedRedirectHandler(allowed_hosts))

    # Wariant polski dokumentacji MS, gdy istnieje — nie wszystkie strony maja
    # tlumaczenie, wiec brak wariantu po prostu zostawia oryginal.
    if try_polish and (wariant := prefer_polish_variant(url)):
        po_polsku = fetch(wariant, allowed_hosts=allowed_hosts, timeout=timeout,
                          max_bytes=max_bytes, opener=opener, try_polish=False)
        if po_polsku["available"]:
            return po_polsku

    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "pl,en;q=0.8",
    })
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(max_bytes + 1)
            status = getattr(response, "status", None) or response.getcode()
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        return _unavailable(url, f"Serwer odpowiedział HTTP {exc.code}: {exc.reason}")
    except urllib.error.URLError as exc:
        return _unavailable(url, f"Nie udało się połączyć: {exc.reason}")
    except (TimeoutError, OSError) as exc:
        return _unavailable(url, f"Błąd sieci: {type(exc).__name__}: {exc}")

    truncated = len(raw) > max_bytes
    body = _decode(raw[:max_bytes], content_type)
    title, text = _extract(body, content_type)
    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS] + "\n[...treść przycięta...]"

    return {
        "available": True,
        "url": url,
        "final_url": final_url,
        "status": status,
        "content_type": content_type,
        "title": title,
        "text": text,
        "bytes": len(raw[:max_bytes]),
        "truncated": truncated,
        "human_url": human_url(final_url),
        "fetched_at": datetime.now().strftime("%d.%m.%Y"),
        "saved_path": _save(url, text),
        "detail": f"Pobrano {len(raw[:max_bytes])} B ze statusem {status}."
                  + (" Treść przycięta do limitu." if truncated else ""),
    }


def main():
    if len(sys.argv) < 2:
        print("Użycie: python web_fetch_worker.py <https://adres> [host1,host2]")
        return 1
    url = sys.argv[1]
    hosts = sys.argv[2].split(",") if len(sys.argv) > 2 else [urlparse(url).hostname]
    result = fetch(url, allowed_hosts=hosts)
    print(json.dumps({k: v for k, v in result.items() if k != "text"}, ensure_ascii=False, indent=2))
    print("--- treść (początek) ---")
    print((result.get("text") or "")[:1000])
    return 0 if result["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
