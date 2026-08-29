"""
Realne wykonanie zadania (nie stub) dla obsługiwanych typów — pierwszy prawdziwy
worker w pętli (M5 w skrócie). Dziś jedna zdolność: walidacja struktury PBIP
(PBI-01), która jest read-only i zielona, więc nadaje się na start autonomii bez
ryzyka. Typy nieobsługiwane zwracają None — runner_loop wraca wtedy do dotychczasowej
ścieżki "sama klasyfikacja/routing", nic nie udając.

Bezpieczeństwo (M1): KAŻDE wykonanie przechodzi przez tool_registry.check_call —
narzędzie musi być w rejestrze kontraktów (config/tool_contracts.yaml), a jego
parametry (w tym ścieżki wobec allowed_roots) muszą pasować do kontraktu. Odmowa
kontraktu = worker nie wykonuje nic (fail-closed). Executor nie trzyma już własnej
listy ścieżek — źródłem prawdy jest kontrakt.
"""

import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

import browser_worker
import integracje_worker
import pbi_desktop_bridge
import pbip_validate
import screenshot_capture
import sharepoint_reader
import tool_registry
import validator_prompt
import web_answer
import web_source_fixer
import web_fetch_worker

SKILL_PATH = Path(__file__).parent / "skills" / "web_research_operations.yaml"


def execute(task):
    """Zwraca execution_result z REALNYM efektem, gdy typ zadania jest obsługiwany,
    albo None, gdy dla tego typu nie ma jeszcze workera."""
    action = (task.get("action") or "").lower()
    if _is_pbip_validation(task):
        return _run_pbip_validation(task)
    if action == "capture_screenshot":
        return _run_screenshot_capture(task)
    if action == "open_pbip_capture":
        return _run_pbip_capture(task)
    if action == "browser_task" or _browser_url_from_task(task):
        return _run_browser_task(task)
    if action == "sharepoint_read" or _sharepoint_url_from_task(task):
        return _run_sharepoint_read(task)
    # Konektory firmowe PRZED fetch_url: zadanie o MailerLite potrafi nieść w
    # opisie zwykły link (np. do panelu), a wtedy trafiłoby do pobierania strony
    # zamiast do właściwego źródła danych.
    if action == "mailerlite_report" or integracje_worker.czy_mailerlite(task):
        return integracje_worker.raport_mailerlite(task)
    if action == "zanfia_query" or integracje_worker.czy_zanfia(task):
        return integracje_worker.podsumowanie_zanfia(task)
    if action == "fetch_url" or _url_from_task(task):
        return _run_web_fetch(task)
    obcy = _url_spoza_allowlisty(task)
    if obcy:
        # Zadanie wskazuje źródło internetowe, którego NIE wolno pobrać. Zwrócenie
        # None kończyło się "zielone bez efektu -> auto done": zadanie zamykane jako
        # zrobione, choć nikt niczego nie zrobił (realnie napotkane). Odmowa z
        # powodem trafia do eskalacji, a właściciel decyduje o dopisaniu domeny.
        return _refused(
            f"Zadanie wskazuje źródło '{obcy}', którego nie ma na allowliście narzędzia fetch_url "
            f"(config/tool_contracts.yaml -> allowed_domains). Nie pobieram niczego spoza listy. "
            f"Decyzja właściciela: dopisać tę domenę do allowlisty albo wskazać inne źródło.",
            tool="fetch_url")
    return None


def rozpoznaj_narzedzie(task):
    """Nazwa narzędzia, którym `execute()` obsłuży to zadanie — bez wykonywania
    niczego (zero efektów ubocznych). Używane PRZED wykonaniem (runner_loop.py),
    żeby risk_hint.hint_from_task wywnioskował kolor z ROZPOZNANEGO narzędzia,
    a nie tylko ze słów w tytule.

    browser_task BEZ browser_steps zwraca 'browser_task_readonly' — bez kroków
    worker mechanicznie może tylko nawigować, zrobić zrzut i odczytać tekst
    (jak fetch_url), więc słowo typu "kampania" w treści nie powinno podnosić
    ryzyka do red. Zadanie Z krokami (klikanie) zostaje jako zwykłe 'browser_task',
    pod normalną klasyfikację słów kluczowych — tam ryzyko jest realne."""
    action = (task.get("action") or "").lower()
    if _is_pbip_validation(task):
        return "validate_pbip"
    if action == "capture_screenshot":
        return "capture_screenshot"
    if action == "open_pbip_capture":
        return "open_pbip_capture"
    if action == "browser_task" or _browser_url_from_task(task):
        return "browser_task" if (task.get("browser_steps") or task.get("kroki")) else "browser_task_readonly"
    if action == "sharepoint_read" or _sharepoint_url_from_task(task):
        return "sharepoint_read"
    if action == "mailerlite_report" or integracje_worker.czy_mailerlite(task):
        return "mailerlite_report"
    if action == "zanfia_query" or integracje_worker.czy_zanfia(task):
        return "zanfia_query"
    if action == "fetch_url" or _url_from_task(task):
        return "fetch_url"
    return None


def _browser_url_from_task(task):
    """Adres wymagający KLIKANIA (nie tylko GET) wyłuskany z treści zadania.
    Domeny browser_task i fetch_url się NIE POKRYWAJĄ (świadomie), więc sam
    host jednoznacznie wskazuje właściwe narzędzie — bez zgadywania z treści,
    które z nich użyć. Zadania z Projectly nie mają pola 'action', więc to
    JEDYNY sposób, żeby zadanie tekstowe trafiło do browser_task."""
    contract = tool_registry.get_contract("browser_task") or {}
    domeny = tool_registry.allowed_domains(contract)
    wskazany = task.get("url")
    if wskazany and web_fetch_worker.host_allowed(wskazany, domeny):
        return wskazany
    tekst = " ".join(str(task.get(p) or "") for p in ("title", "description", "expected_result",
                                                      "acceptance_criteria", "source_file_link"))
    for kandydat in re.findall(r"https://\S+", tekst):
        kandydat = kandydat.rstrip(".,;:!?)\"']")
        if web_fetch_worker.host_allowed(kandydat, domeny):
            return kandydat
    return None


def _sharepoint_url_from_task(task):
    """Adres SharePoint (firmowa organizacja, patrz sharepoint_read w
    tool_contracts.yaml) wyłuskany z treści zadania — ten sam wzorzec co
    _url_from_task/_browser_url_from_task, sprawdzany PRZED nimi, żeby link do
    SharePoint nie trafił do zwykłego fetch_url (nieautoryzowany GET zwróciłby
    tylko stronę logowania, nie realną treść)."""
    contract = tool_registry.get_contract("sharepoint_read") or {}
    domeny = tool_registry.allowed_domains(contract)
    wskazany = task.get("url")
    if wskazany and web_fetch_worker.host_allowed(wskazany, domeny):
        return wskazany
    tekst = " ".join(str(task.get(p) or "") for p in ("title", "description", "expected_result",
                                                      "acceptance_criteria", "source_file_link"))
    for kandydat in re.findall(r"https://\S+", tekst):
        kandydat = kandydat.rstrip(".,;:!?)\"']")
        if web_fetch_worker.host_allowed(kandydat, domeny):
            return kandydat
    return None


def _run_sharepoint_read(task):
    """Odczyt READ-ONLY dowolnej witryny SharePoint firmowej organizacji
    (decyzja właściciela 29.08.2026), z wyjątkiem witryn na liście wykluczeń
    (config/sharepoint.yaml -> read_access.denied_site_paths, np. "Zarządcze").
    Polityka dostępu i parsowanie URL siedzą w sharepoint_reader.py — ten
    worker tylko przekłada wynik na kontrakt execution_result."""
    url = _sharepoint_url_from_task(task)
    if not url:
        return _refused("Zadanie nie wskazuje adresu SharePoint z allowlisty sharepoint_read "
                        "(config/tool_contracts.yaml -> allowed_domains).", tool="sharepoint_read")

    check = tool_registry.check_call("sharepoint_read", {"url": url})
    if not check["allowed"]:
        return _refused(check["reason"], tool="sharepoint_read")

    wynik = sharepoint_reader.read_sharepoint_url(url)
    if not wynik["available"]:
        return _refused(wynik["detail"], tool="sharepoint_read")

    if wynik["kind"] == "file":
        safety = validator_prompt.check_prompt_safety(wynik["text"][:4000])
        if not safety["safe"]:
            return _refused(
                f"Treść pliku '{url}' wygląda na próbę wstrzyknięcia instrukcji "
                f"({safety['detail']}) — treść NIE jest podawana dalej do modelu.",
                tool="sharepoint_read")
        acceptance_notes = f"Odczytano plik SharePoint '{url}':\n\n{wynik['text']}"
    else:
        lista = "\n".join(f"- {'📁' if it['is_folder'] else '📄'} {it['name']}" for it in wynik["items"])
        acceptance_notes = f"Zawartość folderu SharePoint '{url}':\n{lista or '(pusto)'}"

    return {
        "cost_usd": 0.0,  # czysty odczyt Graph, bez modelu
        "tool": "sharepoint_read",
        "executed": True,
        "acceptance_notes": acceptance_notes,
        "source_note": f"SharePoint: {url}",
        "output": wynik,
    }


def _profile_for_url(url, contract):
    """Auto-dobór profilu logowania po hoście adresu (profile_by_domain w
    kontrakcie) — zadanie z Projectly nie ma jak jawnie ustawić browser_profile
    (brak takiego pola w schemacie Projectly), więc profil wynika z domeny."""
    mapping = contract.get("profile_by_domain") or {}
    host = (urlparse(url).hostname or "").lower()
    for domena, profil in mapping.items():
        if host == domena.lower() or host.endswith("." + domena.lower()):
            return profil
    return None


def _url_spoza_allowlisty(task):
    """Pierwszy adres https w treści zadania, którego nie ma na ŻADNEJ znanej
    allowliście (ani fetch_url, ani browser_task) — sygnał, że zadanie wymaga
    źródła, na które nie mamy zgody."""
    tekst = " ".join(str(task.get(p) or "") for p in ("title", "description", "expected_result",
                                                      "acceptance_criteria", "source_file_link"))
    domeny_fetch = tool_registry.allowed_domains(tool_registry.get_contract("fetch_url") or {})
    domeny_browser = tool_registry.allowed_domains(tool_registry.get_contract("browser_task") or {})
    for kandydat in re.findall(r"https://\S+", tekst):
        kandydat = kandydat.rstrip(".,;:!?)\"']")
        if (not web_fetch_worker.host_allowed(kandydat, domeny_fetch)
                and not web_fetch_worker.host_allowed(kandydat, domeny_browser)):
            return kandydat
    return None


def _urls_from_task(task, limit=3):
    """Wszystkie adresy źródeł z treści zadania (z allowlisty), do `limit` sztuk.
    Zadanie potrafi wskazać kilka źródeł naraz ("porównaj kurs EUR i USD")."""
    wskazany = task.get("url")
    if isinstance(wskazany, list):
        return wskazany[:limit]
    if wskazany:
        return [wskazany]

    tekst = " ".join(str(task.get(p) or "") for p in ("title", "description", "expected_result",
                                                      "acceptance_criteria", "source_file_link"))
    domeny = tool_registry.allowed_domains(tool_registry.get_contract("fetch_url") or {})
    znalezione = []
    for kandydat in re.findall(r"https://\S+", tekst):
        kandydat = kandydat.rstrip(".,;:!?)\"']")
        if web_fetch_worker.host_allowed(kandydat, domeny) and kandydat not in znalezione:
            znalezione.append(kandydat)
    return znalezione[:limit]


def _url_from_task(task):
    """Adres źródła wyłuskany z treści zadania. Zadania z Projectly nie mają pola
    'url' — niosą adres w tytule albo opisie. Bierzemy TYLKO adresy z allowlisty
    kontraktu: dzięki temu zwykły link w opisie (SharePoint, załącznik) nie
    uruchamia pobierania, a zadanie bez pasującego źródła idzie dotychczasową
    ścieżką zamiast produkować odmowę."""
    if task.get("url"):
        return task["url"]
    tekst = " ".join(str(task.get(p) or "") for p in ("title", "description", "expected_result",
                                                      "acceptance_criteria", "source_file_link"))
    domeny = tool_registry.allowed_domains(tool_registry.get_contract("fetch_url") or {})
    # Przecinek MUSI być dozwolony w środku adresu — parametry API mają postać
    # "daily=temperature_2m_max,temperature_2m_min,precipitation_sum". Wycinanie
    # go z zakresu znaków ucinało adres w połowie, więc model dostawał inne dane
    # niż zamówione (realnie: brak opadów i minimum w zadaniu o pogodzie).
    for kandydat in re.findall(r"https://\S+", tekst):
        kandydat = kandydat.rstrip(".,;:!?)\"']")
        if web_fetch_worker.host_allowed(kandydat, domeny):
            return kandydat
    return None


def _is_pbip_validation(task):
    if (task.get("action") or "").lower() == "validate_pbip":
        return True
    title = (task.get("title") or "").lower()
    return "pbip" in title and any(w in title for w in ("waliduj", "walidacj", "sprawdź struktur"))


def _run_pbip_validation(task):
    raw_path = task.get("project_path") or task.get("source_file_link")

    # M1: bramka kontraktu PRZED jakimkolwiek dostępem do plików. Rejestr sprawdza
    # allowlistę narzędzia, wymagane parametry i allowed_roots dla ścieżki.
    check = tool_registry.check_call("validate_pbip", {"project_path": raw_path})
    if not check["allowed"]:
        return _refused(check["reason"])

    project_dir = Path(raw_path)
    if not project_dir.exists():
        return _refused(f"Ścieżka '{raw_path}' nie istnieje.")

    result = pbip_validate.validate_pbip(project_dir)
    passed = not result["errors"]
    target = str(project_dir)
    report = _build_report(project_dir, result, passed)
    return {
        "cost_usd": 0.0,  # czysta walidacja plików, bez modelu
        "tool": "validate_pbip",
        "executed": True,
        "acceptance_notes": report,  # pełny mini-raport, nie jedno zdanie (odbiór biznesowy)
        "output": result,  # sygnatura efektu dla Bartka (porównanie dwóch przebiegów)
        # Franek: twardy test funkcjonalny na realnym efekcie (ponowna walidacja pliku).
        "functional_checks": [
            {"name": "Walidacja struktury PBIP", "type": "pbip_valid", "target": target},
        ],
        # Bartek: drugi niezależny przebieg tej samej walidacji (kontrola determinizmu).
        "rerun": lambda: pbip_validate.validate_pbip(target),
    }


def _screenshot_effect(shot, tool, ok_notes, fail_notes):
    """Wspólny kształt execution_result dla zadań, których efektem jest ZRZUT
    ekranu — karmi Oskara (kontrola wizualna) i Franka (nonempty_file na PNG)."""
    if not shot["available"]:
        # Brak zrzutu to nie odmowa bezpieczeństwa, tylko luka zdolności —
        # przechodzi przez bramkę uczciwie (Oskar pominie brak zrzutu).
        return {"cost_usd": 0.0, "tool": tool, "executed": True,
                "acceptance_notes": f"{fail_notes} Szczegół: {shot['detail']}"}
    return {
        "cost_usd": 0.0,
        "tool": tool,
        "executed": True,
        "acceptance_notes": f"{ok_notes} Zrzut: {shot['screenshot_path']}",
        "screenshot_path": shot["screenshot_path"],
        "functional_checks": [
            {"name": "Zrzut ekranu zapisany", "type": "nonempty_file", "target": shot["screenshot_path"]},
        ],
    }


def _run_screenshot_capture(task):
    """Zrzut ekranu/okna jako efekt zadania (np. 'pokaż stan aplikacji X')."""
    out_dir = task.get("out_dir")
    check = tool_registry.check_call("capture_screenshot", {"out_dir": out_dir})
    if not check["allowed"]:
        return _refused(check["reason"], tool="capture_screenshot")

    window_title = task.get("window_title")
    if window_title:
        shot = screenshot_capture.capture_window(window_title)
        # capture_window zwraca {available, path, ...}; ujednolicamy do kształtu bridge.
        shot = {"available": shot["available"], "screenshot_path": shot.get("path"), "detail": shot["detail"]}
    else:
        raw = screenshot_capture.capture_screen()
        shot = {"available": raw["available"], "screenshot_path": raw.get("path"), "detail": raw["detail"]}
    return _screenshot_effect(shot, "capture_screenshot",
                              "Zrzut ekranu wykonany.", "Nie udało się wykonać zrzutu.")


def _run_pbip_capture(task):
    """Otwiera PBIP w Power BI Desktop i robi zrzut okna raportu (PBI-01, dalszy
    etap po walidacji struktury) — dostarcza screenshot_path do kontroli wizualnej."""
    raw_path = task.get("project_path") or task.get("source_file_link")
    check = tool_registry.check_call("open_pbip_capture", {"project_path": raw_path})
    if not check["allowed"]:
        return _refused(check["reason"], tool="open_pbip_capture")

    shot = pbi_desktop_bridge.open_and_capture(raw_path)
    result = _screenshot_effect(shot, "open_pbip_capture",
                                "Otwarto PBIP i wykonano zrzut strony raportu.",
                                "Otwarcie/zrzut raportu nie powiodły się.")
    result["tool"] = "open_pbip_capture"
    return result


def _run_browser_task(task):
    """Zadanie webowe wymagające KLIKANIA/wypełniania (Playwright headless) — tam,
    gdzie fetch_url (czysty GET) nie wystarcza. Adres rozpoznawany przez
    _browser_url_from_task (jawne action=='browser_task' ALBO domena z treści
    zadania pasująca do allowlisty browser_task — domeny fetch_url/browser_task
    się nie pokrywają, więc host jednoznacznie wskazuje właściwe narzędzie).

    Allowlista hostów siedzi w kontrakcie `browser_task` (config/tool_contracts.yaml),
    tak samo jak przy fetch_url — właściciel dopisuje domenę świadomie. Profil
    logowania (browser_profile) dobiera się automatycznie po domenie
    (profile_by_domain), bo Projectly nie ma pola na jawne ustawienie profilu."""
    contract = tool_registry.get_contract("browser_task") or {}
    url = _browser_url_from_task(task)
    if not url:
        return _refused("Zadanie nie wskazuje adresu z allowlisty browser_task "
                        "(config/tool_contracts.yaml -> browser_task.allowed_domains).", tool="browser_task")

    profile = task.get("browser_profile") or _profile_for_url(url, contract)
    check = tool_registry.check_call("browser_task", {"url": url, "browser_profile": profile})
    if not check["allowed"]:
        return _refused(check["reason"], tool="browser_task")

    if profile and profile not in (contract.get("allowed_profiles") or []):
        return _refused(
            f"Profil logowania '{profile}' nie jest na allowliście narzędzia browser_task "
            f"(config/tool_contracts.yaml -> allowed_profiles) — odmowa (fail-closed).",
            tool="browser_task")

    steps = task.get("browser_steps") or task.get("kroki") or []
    domeny = tool_registry.allowed_domains(contract)

    wynik = browser_worker.run(url, steps=steps, allowed_hosts=domeny, profile=profile)
    if not wynik["available"]:
        return _refused(wynik["detail"], tool="browser_task")

    # Tekst strony jest z definicji NIEZAUFANY (tak samo jak przy fetch_url) —
    # kontrola wstrzyknięcia instrukcji PRZED podaniem go dalej do modelu.
    page_text = wynik.get("page_text") or ""
    if page_text:
        safety = validator_prompt.check_prompt_safety(page_text[:4000])
        if not safety["safe"]:
            return _refused(
                f"Treść strony '{url}' wygląda na próbę wstrzyknięcia instrukcji "
                f"({safety['detail']}) — treść NIE jest podawana dalej do modelu.",
                tool="browser_task")

    # Sam zrzut/nawigacja to jeszcze nie wykonanie zadania — model odpowiada na
    # pytanie z tytułu na podstawie tekstu strony, dokładnie jak _run_web_fetch
    # robi to dla fetch_url (web_answer.py, ten sam mechanizm, inne źródło).
    answer = (web_answer.answer(task.get("title", ""), page_text, url=wynik["final_url"],
                                zrodlo_opis=wynik.get("title") or wynik["final_url"])
              if page_text else {"available": False, "detail": "brak tekstu ze strony"})

    if answer.get("available"):
        acceptance_notes = answer["answer"]
        koszt = answer.get("cost_usd", 0.0)
    else:
        # Bez modelu/tekstu nie ma opracowanej odpowiedzi — mówimy to wprost,
        # zamiast udawać gotowy materiał (ten sam wzorzec co _build_web_report).
        powod = answer.get("detail", "brak modelu")
        acceptance_notes = (
            f"UWAGA: nie udało się opracować odpowiedzi ({powod}) — wykonano "
            f"{wynik['steps_done']}/{wynik['steps_total']} kroków na stronie "
            f"'{wynik.get('title') or wynik['final_url']}'. Zrzut: {wynik['screenshot_path']}")
        koszt = 0.0

    return {
        "cost_usd": koszt,
        "tool": "browser_task",
        "executed": True,
        "acceptance_notes": acceptance_notes,
        "screenshot_path": wynik["screenshot_path"],
        "output": {"final_url": wynik["final_url"], "title": wynik["title"],
                   "steps_done": wynik["steps_done"], "steps_total": wynik["steps_total"]},
        "functional_checks": [
            {"name": "Zrzut po wykonaniu kroków zapisany", "type": "nonempty_file",
             "target": wynik["screenshot_path"]},
        ],
        # Świadomie BEZ `rerun`: kroki mogą mieć efekty uboczne (klik "Wyślij",
        # wypełnienie formularza) — ponowne odpalenie do kontroli determinizmu
        # (Bartek) mogłoby powtórzyć akcję, której nie wolno powtórzyć. Kontrola
        # determinizmu dla tego workera wymaga podejścia per-krok (Faza 3+),
        # nie ślepego uruchomienia tej samej sekwencji drugi raz.
    }


def _run_web_fetch(task):
    """Pobranie informacji z internetu (read-only GET). Allowlista hostów siedzi
    w kontrakcie `fetch_url` — executor nie trzyma własnej listy, tak samo jak
    przy ścieżkach plików.

    Zadanie może wskazywać KILKA źródeł (np. "porównaj kurs EUR i USD") — wtedy
    pobieramy każde i model dostaje wszystkie treści naraz. Wcześniej brany był
    tylko pierwszy adres, więc zadanie porównawcze nie miało z czego powstać.

    Treść z internetu jest z definicji NIEZAUFANA, więc zanim trafi do modelu
    przechodzi przez kontrolę wstrzyknięcia instrukcji. Wykrycie = odmowa
    z eskalacją, nie 'ostrzeżenie w raporcie'."""
    urls = _urls_from_task(task)
    if not urls:
        return _refused("Zadanie nie wskazuje adresu źródła do pobrania.", tool="fetch_url")

    contract = tool_registry.get_contract("fetch_url") or {}
    domeny = tool_registry.allowed_domains(contract)

    wyniki = []
    for url in urls:
        check = tool_registry.check_call("fetch_url", {"url": url})
        if not check["allowed"]:
            return _refused(check["reason"], tool="fetch_url")
        wyniki.append(web_fetch_worker.fetch(url, allowed_hosts=domeny))

    # Błąd źródła nie zawsze znaczy, że zadania nie da się wykonać: skill może
    # znać adres zastępczy (np. NBP nie publikuje tabeli w dni wolne, więc bierzemy
    # ostatnie notowanie). Próbujemy RAZ, a adnotacja mówi modelowi, że dane są
    # z innego dnia i musi to napisać wprost.
    if not task.get("_po_fallbacku"):
        for i, wynik in enumerate(wyniki):
            if wynik["available"]:
                continue
            kod = re.search(r"HTTP (\d{3})", wynik.get("detail") or "")
            if not kod:
                continue
            zastepczy, adnotacja = web_source_fixer.fallback_po_bledzie(wynik["url"], int(kod.group(1)))
            if zastepczy:
                nowe_urls = list(urls)
                nowe_urls[i] = zastepczy
                return _run_web_fetch({**task, "url": nowe_urls, "_po_fallbacku": True,
                                       "_adnotacja_zrodla": adnotacja})

    udane = [w for w in wyniki if w["available"]]
    if not udane:
        # Komunikat dla CZŁOWIEKA, nie zrzut techniczny: bez adresu API, bez kodów
        # HTTP i angielskich fraz. Odbiór biznesowy słusznie odrzucał materiał,
        # w którym stało "HTTP 404: Not Found" i pełny link z parametrem format=json.
        return {"cost_usd": 0.0, "tool": "fetch_url", "executed": True,
                "acceptance_notes": "NIE WYKONANO — " + " ".join(_powod_po_ludzku(w) for w in wyniki),
                "output": {"zrodla": [_web_signature(w) for w in wyniki]}}

    for wynik in udane:
        safety = validator_prompt.check_prompt_safety(wynik["text"][:4000])
        if not safety["safe"]:
            return _refused(
                f"Pobrana treść z '{wynik['url']}' wygląda na próbę wstrzyknięcia instrukcji "
                f"({safety['detail']}) — treść NIE jest podawana dalej do modelu. "
                f"Plik: {wynik['saved_path']}",
                tool="fetch_url")

    # Dwa adresy z tego samego serwisu dawały "NBP...; NBP..." w stopce — etykiety
    # deduplikujemy z zachowaniem kolejności.
    etykiety = "; ".join(dict.fromkeys(_source_label(w) for w in udane))
    tresc_zrodel = "\n\n".join(
        f"=== ŹRÓDŁO {i}: {_source_label(w)} ===\n{w['text']}" for i, w in enumerate(udane, 1)
    ) if len(udane) > 1 else udane[0]["text"]

    # Samo pobranie to jeszcze nie wykonanie zadania — model odpowiada na pytanie
    # z tytułu zadania na podstawie treści. Model dostaje OPIS źródła, nie surowy
    # adres, żeby mógł doprecyzować, czym są dane (np. że to kurs średni z tabeli A).
    pytanie = task.get("title", "")
    adnotacja = task.get("_adnotacja_zrodla")
    if adnotacja:
        # Dane pochodzą z adresu zastępczego — model musi wiedzieć, czym się różnią
        # od zamówionych, żeby nie podał ich jako danych z zamówionego dnia.
        pytanie = f"{pytanie}\n\nWAŻNE o danych, które dostajesz: {adnotacja}"

    answer = web_answer.answer(pytanie, tresc_zrodel, url=udane[0]["url"], zrodlo_opis=etykiety)

    tresc = (answer.get("answer") or "").strip()
    if answer.get("available") and tresc.startswith("BRAK_ODPOWIEDZI_W_ZRODLE"):
        # Zanim oddamy zadanie człowiekowi: jeśli skill zna regułę korekty adresu
        # (np. inna waluta w tej samej tabeli NBP), poprawiamy adres i próbujemy
        # RAZ jeszcze. Flaga _po_korekcie blokuje pętlę.
        tekst_zadania = " ".join(str(task.get(k) or "") for k in ("title", "description"))
        if not task.get("_po_korekcie"):
            lepsze = [web_source_fixer.popraw_adres(w["url"], tekst_zadania) for w in udane]
            lepsze = [a for a in lepsze if a]
            if lepsze:
                return _run_web_fetch({**task, "url": lepsze, "_po_korekcie": True})

        powod = tresc.split(":", 1)[1].strip() if ":" in tresc else tresc
        powod = powod[:1].upper() + powod[1:] if powod else powod
        return {
            "cost_usd": answer.get("cost_usd", 0.0),
            "tool": "fetch_url",
            "executed": True,
            "acceptance_notes": (f"NIE WYKONANO — wskazane źródło nie zawiera odpowiedzi na to zadanie. "
                                 f"{powod} Żeby dokończyć, potrzebuję źródła z tymi danymi."),
            "output": {"zrodla": [_web_signature(w) for w in udane]},
        }

    sygnatura = {"zrodla": [_web_signature(w) for w in udane]}
    return {
        "cost_usd": answer.get("cost_usd", 0.0),
        "tool": "fetch_url",
        "executed": True,
        "acceptance_notes": _build_web_report(udane[0], answer),
        # Pochodzenie danych trafia do komentarza, NIE do materiału — odbiorca
        # dostaje czysty tekst do przeklejenia, audyt i tak wie, skąd dane.
        # Każde źródło w osobnej linii — sklejone przecinkiem sugerowały, że cały
        # materiał pochodzi z pierwszego z nich (realna uwaga przy notatce
        # łączącej kurs waluty z prognozą pogody).
        "source_note": "\n".join(
            f"{_source_label(w)} (pobrano {w.get('fetched_at', 'dziś')})"
            for w in {_source_label(x): x for x in udane}.values()),
        "output": sygnatura,
        "functional_checks": [
            {"name": f"Pobrana treść zapisana na dysku ({_source_label(w)})",
             "type": "nonempty_file", "target": w["saved_path"]} for w in udane
        ],
        # Bartek porównuje SYGNATURY, więc rerun musi zwracać dokładnie ten sam
        # kształt co `output` — inaczej każde zadanie wygląda na niedeterministyczne.
        "rerun": lambda: {"zrodla": [_web_signature(web_fetch_worker.fetch(w["url"], allowed_hosts=domeny))
                                     for w in udane]},
    }


def _web_signature(result):
    """Sygnatura pobrania do kontroli regresji (Bartek): CO odpowiedziało źródło,
    a nie co dokładnie było w treści. Żywe strony zmieniają w każdej odpowiedzi
    identyfikatory i znaczniki czasu (np. pole `tid` w API Wikipedii), więc
    porównywanie pełnej treści dawałoby stały fałszywy alarm 'niedeterminizm'.
    Merytoryczną zawartość ocenia Franek (plik)."""
    if not result.get("available"):
        return {"available": False, "url": result.get("url"), "detail": result.get("detail")}
    return {
        "available": True,
        "url": result["url"],
        "final_url": result["final_url"],
        "human_url": result.get("human_url"),
        "status": result["status"],
        "content_type": result["content_type"],
        "title": result["title"],
    }


def _source_label(result):
    """Opis źródła dla człowieka: nazwa instytucji z kontraktu + klikalny link
    w nawiasie. Sam adres API jest dla odbiorcy nieczytelny — realna uwaga
    z odbioru biznesowego ("chcę 'NBP, tabela nr ...', link może być w nawiasie")."""
    link = result.get("human_url") or result.get("url") or ""
    host = urlparse(link).hostname or ""
    nazwy = (tool_registry.get_contract("fetch_url") or {}).get("source_names") or {}
    nazwa = nazwy.get(host)
    # Adres endpointu API w materiale dla odbiorcy "wygląda technicznie i roboczo"
    # (uwaga odbioru biznesowego) — link podajemy tylko wtedy, gdy da się go
    # otworzyć i zrozumieć: bez /api/ i bez parametrów zapytania.
    # Publiczny odpowiednik adresu (strona, na której dane widać) — dla API bez
    # czytelnego adresu bierzemy go ze skilla, żeby odbiorca miał co kliknąć.
    publiczny = _link_publiczny(host)
    czytelny = link and "/api/" not in link and "?" not in link
    if nazwa and publiczny:
        return f"{nazwa} — {publiczny}"
    if nazwa and czytelny:
        return f"{nazwa} — {link}"
    return nazwa or link


def _powod_po_ludzku(wynik):
    """Dlaczego nie udało się pobrać danych — językiem odbiorcy. Kod odpowiedzi
    serwera tłumaczymy na wyjaśnienie ze skilla (np. że NBP nie publikuje tabeli
    w dni wolne); gdy skill nic nie wie, mówimy krótko, co się stało."""
    host = (urlparse(wynik.get("url") or "").hostname or "").lower()
    nazwa = _nazwa_zrodla(host) or "wskazane źródło"

    kod = re.search(r"HTTP (\d{3})", wynik.get("detail") or "")
    if kod:
        wyjasnienie = _wyjasnienie_bledu(host, int(kod.group(1)))
        if wyjasnienie:
            return f"{nazwa}: {wyjasnienie}"
        return f"{nazwa} nie udostępniło danych pod wskazanym adresem (odpowiedź serwera {kod.group(1)})."
    return f"Nie udało się połączyć ze źródłem {nazwa}."


def _wpis_skilla(host):
    try:
        dane = yaml.safe_load(SKILL_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return (dane.get("zrodla") or {}).get(host) or {}


def _nazwa_zrodla(host):
    return _wpis_skilla(host).get("nazwa")


def _wyjasnienie_bledu(host, kod):
    return (_wpis_skilla(host).get("bledy") or {}).get(kod)


def _link_publiczny(host):
    """Strona do pokazania człowiekowi zamiast adresu API (skill web_research_operations)."""
    try:
        dane = yaml.safe_load(SKILL_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    wpis = (dane.get("zrodla") or {}).get(host) or {}
    return wpis.get("link_publiczny")


def _build_web_report(result, answer=None):
    """CZYSTY materiał dla odbiorcy — dokładnie to, co zamówiono, i nic więcej.

    Żadnej stopki, separatora ani danych technicznych: pochodzenie danych jedzie
    osobnym polem `source_note` do komentarza, a status HTTP i ścieżka pliku
    zostają w `output` i w kontroli funkcjonalnej. Odbiór biznesowy odrzucał
    materiał za każdym razem, gdy pod zamówionym tekstem stało cokolwiek jeszcze
    ("muszę to ręcznie skasować przed wysłaniem, a właśnie tego chciałam uniknąć")."""
    if answer and answer.get("available"):
        return answer["answer"]

    # Bez modelu nie ma opracowanej odpowiedzi — oddajemy surową treść, ale mówimy
    # wprost, że to materiał do samodzielnej oceny, a nie gotowy efekt.
    powod = answer["detail"] if answer else "brak modelu"
    return "\n".join([
        f"UWAGA: nie udało się opracować odpowiedzi modelem ({powod}) — poniżej surowa treść źródła.",
        "",
        result["text"][:1500],
    ])


def _build_report(project_dir, result, passed):
    """Czytelny raport walidacji: CO sprawdzono, ILE plików, jakie błędy/ostrzeżenia.
    Bez tego odbiór biznesowy słusznie odrzuca ('jedno zdanie to nie raport')."""
    pbip = [f.name for f in project_dir.glob("*.pbip")]
    reports = [f.name for f in project_dir.glob("*.Report")]
    models = [f.name for f in project_dir.glob("*.SemanticModel")]
    tmdl_count = sum(len(list((m / "definition").rglob("*.tmdl"))) for m in project_dir.glob("*.SemanticModel"))

    lines = [
        f"Raport walidacji struktury PBIP — {project_dir.name}",
        f"Wynik: {'POPRAWNA' if passed else 'BŁĘDY'} — {len(result['errors'])} błędów, {len(result['warnings'])} ostrzeżeń.",
        "Sprawdzono:",
        f"  - pliki .pbip (poprawność JSON): {', '.join(pbip) or 'brak'}",
        f"  - foldery .Report (definition.pbir / report.json): {', '.join(reports) or 'brak'}",
        f"  - foldery .SemanticModel (pliki TMDL): {', '.join(models) or 'brak'} — {tmdl_count} {'plik' if tmdl_count == 1 else 'plików'} .tmdl",
    ]
    if result["errors"]:
        lines.append("Błędy:")
        lines.extend(f"  - {e}" for e in result["errors"])
    if result["warnings"]:
        lines.append("Ostrzeżenia:")
        lines.extend(f"  - {w}" for w in result["warnings"])
    return "\n".join(lines)


def _refused(reason, tool="validate_pbip"):
    """Odmowa wykonania (np. ścieżka poza workspace). Runner obsługuje ją WPROST
    jako eskalację bezpieczeństwa — nie podajemy złej ścieżki dalej do bramki."""
    return {
        "cost_usd": 0.0,
        "tool": tool,
        "executed": False,
        "acceptance_notes": reason,
        "output": {"refused": reason},
    }
