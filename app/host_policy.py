"""
Jedna polityka hostów dla całego internetu agenta.

Decyzja właściciela 05.09.2026: **wszystkie normalne witryny są zatwierdzone**.
Nie prowadzimy listy wyjątków, bo prowadzenie jej kosztowało realną pracę:
agent marketingowy dostał zadanie "pobierz sekcję dofinansowań ze strony
ldit.pl" i odmówił, bo ldit.pl (strona realnego klienta) nie była wpisana na
allowlistę fetch_url. Zadanie skończyło się eskalacją do człowieka zamiast
wynikiem.

Zostają DWA twarde ograniczenia, i tylko one:
  1. https (nie http), jak dotąd, sprawdzane u wołających,
  2. darknet i adresy wewnętrzne maszyny/sieci są zablokowane ZAWSZE, także
     przy allowliście "*". Darknet, bo właściciel powiedział wprost, że tam nie
     wchodzimy. Adresy wewnętrzne (localhost, 10.x, 192.168.x, link-local), bo
     to nie są "witryny internetowe" tylko panele tej maszyny (dashboard na
     127.0.0.1:8787, Ollama na 11434). Adres do pobrania wybiera model na
     podstawie treści zadania, więc bez tej blokady wystarczyłby spreparowany
     opis zadania, żeby wyciągnąć zawartość panelu wewnętrznego.

Ten moduł jest CELOWO bez zależności (tylko stdlib): korzysta z niego zarówno
warstwa kontraktów (tool_registry.py), jak i workery sieciowe
(web_fetch_worker.py, przez nie browser_worker.py). Gdyby polityka siedziała w
którymś z workerów, warstwa kontraktów musiałaby importować worker, czyli
zależność w złą stronę.
"""

import ipaddress
from urllib.parse import urlparse

# Wpis w allowed_domains oznaczający "każda normalna witryna".
WSZYSTKIE_DOMENY = "*"

# Darknet: sieci, do których i tak nie ma zwykłego dostępu, a wejście na nie
# nigdy nie jest tym, o co prosi zadanie biznesowe.
KONCOWKI_DARKNET = (".onion", ".i2p")

# Nazwy hostów wskazujące na tę samą maszynę.
HOSTY_LOKALNE = ("localhost", "localhost.localdomain", "ip6-localhost")


def _host_wewnetrzny(host):
    """Czy host wskazuje na tę maszynę albo sieć lokalną (nie na internet)."""
    if host in HOSTY_LOKALNE:
        return True
    try:
        adres = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        return False
    return (adres.is_private or adres.is_loopback or adres.is_link_local
            or adres.is_reserved or adres.is_multicast)


def powod_blokady(url):
    """Powód, dla którego tego adresu nie wolno odwiedzić NIGDY (także przy
    allowliście "*"), albo None gdy adres jest zwyczajny."""
    host = (urlparse(url or "").hostname or "").lower()
    if not host:
        return "adres bez hosta"
    if host.endswith(KONCOWKI_DARKNET):
        return "adres w sieci darknet (decyzja właściciela: tam nie wchodzimy)"
    if _host_wewnetrzny(host):
        return "adres wewnętrzny tej maszyny/sieci lokalnej, nie jest witryną internetową"
    return None


def host_dozwolony(url, allowed_hosts):
    """Czy wolno odwiedzić ten adres przy tej allowliście.

    Pusta allowlista = odmowa (fail-closed, jak dotąd). Wpis "*" = każda normalna
    witryna. Bez "*" działa jak przedtem: dokładne dopasowanie albo subdomena
    (sam sufiks nie wystarcza, "api.nbp.pl.atakujacy.example" nie przechodzi
    jako "api.nbp.pl")."""
    if not allowed_hosts:
        return False
    if powod_blokady(url):
        return False
    host = (urlparse(url or "").hostname or "").lower()
    if WSZYSTKIE_DOMENY in allowed_hosts:
        return True
    return any(host == d.lower() or host.endswith("." + d.lower()) for d in allowed_hosts)


def wszystkie_dozwolone(allowed_hosts):
    """Czy ta allowlista otwiera cały internet (do komunikatów dla człowieka)."""
    return WSZYSTKIE_DOMENY in (allowed_hosts or [])
