"""
Bożena — odbiór biznesowy.

Funkcja: wciela się w biurowego użytkownika biznesowego po stronie klienta i
ocenia, czy efekt zadania to NA PEWNO to, czego oczekiwał — wg jego wiedzy
biznesowej i kryteriów akceptacji, a nie tylko "czy technicznie działa". To
ostatni głos przed człowiekiem: jeśli Bożena nie powie "tak", zadanie nie idzie
dalej jako gotowe (Bożena jest botem obowiązkowym w bramce — patrz
config/validation_gate.yaml).

Skąd bierze wiedzę (składane od ogólnej do szczegółowej):
- persona biznesowa (persony_botow/bozena_biznes.md) — ton i pryzmat oceny.
  UWAGA: to persona BOTA (jak ma oceniać), nie buyer persona klienta — te są
  w app/kontekst/persony/ (patrz docs/buyer-persony.html). Nazwy rozdzielone
  celowo po realnej kolizji (dwa różne "personas"/"persony" w repo).
- kontekst biznesowy (config/business_context.yaml) — default -> typ zadania -> klient,
- kryteria akceptacji z samego zadania.

Ocena idzie przez model (task_thinker.ask_model: Claude Code -> SDK -> Ollama).
Brak modelu = `skipped` — a że Bożena jest obowiązkowa, bramka wtedy eskaluje do
człowieka (fail-closed: nie potwierdzamy odbioru bez oceny).

Kontrakt: patrz bot_common.py.
"""

import re
from pathlib import Path

import yaml

import kontekst_firmy
import task_thinker
from bot_common import verdict

BOT = "bozena"

CONTEXT_PATH = Path(__file__).parent / "config" / "business_context.yaml"
USTALENIA_PATH = Path(__file__).parent / "config" / "odbior_ustalenia.yaml"
PERSONA_PATH = Path(__file__).parent / "persony_botow" / "bozena_biznes.md"


def load_ustalenia(path=USTALENIA_PATH):
    """Zasady odbioru: co blokuje, co jest sugestią, co już rozstrzygnięto.
    Bez nich ocena była za każdym razem nowa i potrafiła sobie przeczyć."""
    try:
        return yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}


def load_persona(path=PERSONA_PATH):
    return path.read_text(encoding="utf-8") if path.exists() else ""


def load_business_context(task, path=CONTEXT_PATH):
    """Składa kontekst: default -> per_typ_zadania[typ] -> klienci[dopasowany].
    Warstwy się DOKŁADAJĄ (bardziej szczegółowa nie kasuje ogólnej)."""
    if not path.exists():
        return {"oczekiwania": "", "na_co_uwaga": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    oczekiwania = []
    na_co_uwaga = []

    def _absorb(layer):
        if not layer:
            return
        if layer.get("oczekiwania"):
            oczekiwania.append(layer["oczekiwania"].strip())
        na_co_uwaga.extend(layer.get("na_co_uwaga", []))

    _absorb(data.get("default"))
    _absorb((data.get("per_typ_zadania") or {}).get(task.get("action_type")))

    title = (task.get("title") or "").lower()
    for client, layer in (data.get("klienci") or {}).items():
        if client.lower() in title:
            _absorb(layer)

    return {"oczekiwania": " ".join(oczekiwania), "na_co_uwaga": na_co_uwaga}


def _lista(punkty, pusto="- (brak)"):
    return "\n".join(f"- {p}" for p in (punkty or [])) or pusto


def build_prompt(task, execution_result, context, persona, ustalenia=None):
    ustalenia = ustalenia or {}
    uwagi = _lista(context["na_co_uwaga"], "- (brak dodatkowych)")
    zasady = (
        "--- CO WSTRZYMUJE ZADANIE (tylko te rzeczy dają AKCEPTACJA: nie) ---\n"
        f"{_lista(ustalenia.get('blokujace'))}\n\n"
        "--- CO NIE WSTRZYMUJE ZADANIA (zgłoś jako SUGESTIE, nie jako powód odmowy) ---\n"
        f"{_lista(ustalenia.get('nie_blokuje'))}\n\n"
        "--- KWESTIE JUŻ ROZSTRZYGNIĘTE (respektuj, nie oceniaj ich od nowa) ---\n"
        f"{_lista(ustalenia.get('ustalenia'))}\n\n"
    ) if ustalenia else ""
    # Odbiór ocenia materiał w realiach firmy, nie w próżni: inaczej wymagałby
    # od materiału marki szkoleniowej rzeczy właściwych dla wdrożeniowej.
    firma = kontekst_firmy.zbuduj(" ".join(str(task.get(k) or "") for k in ("title", "description")))
    return (
        f"{persona}\n\n"
        + (f"{firma}\n\n" if firma else "")
        + "--- KONTEKST BIZNESOWY (czego oczekuje użytkownik) ---\n"
        f"{context['oczekiwania']}\n"
        f"Na co zwrócić szczególną uwagę:\n{uwagi}\n\n"
        "--- ZADANIE ---\n"
        f"Tytuł: {task.get('title')}\n"
        f"Oczekiwany rezultat: {task.get('expected_result')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria')}\n\n"
        f"{_dopisek_o_zrodlach(execution_result)}"
        f"{_dopisek_o_personie(execution_result)}"
        "--- CO BOT WYKONAŁ (efekt do oceny — oceniasz WYŁĄCZNIE to, co jest między znacznikami) ---\n"
        "[POCZĄTEK MATERIAŁU]\n"
        f"{execution_result.get('acceptance_notes') or execution_result.get('output') or '(brak opisu efektu)'}\n"
        "[KONIEC MATERIAŁU]\n\n"
        f"{zasady}"
        "Oceń, czy to jest efekt, jakiego oczekiwałby użytkownik biznesowy.\n"
        "AKCEPTACJA: nie — TYLKO gdy wskażesz co najmniej jedno zastrzeżenie z listy blokujących.\n"
        "Drobiazgi stylistyczne i propozycje rozszerzeń zgłaszaj w SUGESTIE, a mimo nich daj AKCEPTACJA: tak.\n"
        "Odpowiedz w formacie:\n"
        "AKCEPTACJA: tak|nie\n"
        "UZASADNIENIE: <1-3 zdania>\n"
        "ZASTRZEŻENIA BLOKUJĄCE:\n- <konkret albo 'brak'>\n"
        "SUGESTIE:\n- <konkret albo 'brak'>"
    )


def _dopisek_o_zrodlach(execution_result):
    """Pochodzenie danych system dokleja POZA materiałem (osobne pole komentarza),
    więc bez tej informacji odbiór biznesowy zarzucał brak źródeł, których po prostu
    nie widział — i odrzucał poprawny efekt. Pokazujemy je wprost, z zaznaczeniem,
    że nie są częścią materiału i nie trzeba ich powtarzać w treści."""
    zrodla = execution_result.get("source_note")
    if not zrodla:
        return ""
    # Bez tej informacji odbiór zarzucał brak źródeł, których po prostu nie widział.
    # Ale gdy sekcja wyglądała tak samo jak blok z materiałem, ocena szła w drugą
    # stronę: model uznawał ją ZA CZĘŚĆ materiału i odrzucał za "stopkę w treści".
    # Dlatego stoi PRZED materiałem i jest wcięta, a materiał ma własne znaczniki.
    wciete = "\n".join(f"    {linia}" for linia in str(zrodla).splitlines())
    return ("INFORMACJA DLA CIEBIE (to NIE jest część materiału — system dokleja pochodzenie danych\n"
            "do zadania osobno; nie oczekuj tego w treści i nie oceniaj tego):\n"
            f"{wciete}\n\n")


def _dopisek_o_personie(execution_result):
    """Gdy material celuje w konkretną buyer personę (execution_result niesie
    target_persona + persona_brand — dwie marki mają persony o TYM SAMYM imieniu,
    np. "Tomek", więc marka jest wymagana do bezpiecznego dopasowania), dołączamy
    PRAWDZIWY profil tej osoby: cele, obiekcje, czego unika, co ją przekonuje.

    Bez tego Bożena oceniała material generycznie ("czy JA bym to wzięła"), a nie
    względem konkretnego adresata, dla którego material realnie jest pisany —
    a to jest sedno odbioru biznesowego dla treści marketingowych, nie ogólna
    poprawność (realna uwaga właściciela 21.08.2026)."""
    target = execution_result.get("target_persona")
    brand = execution_result.get("persona_brand") or execution_result.get("brand")
    if not target:
        return ""
    plik = kontekst_firmy.dopasuj_persone(target, brand)
    if not plik:
        return ""
    try:
        profil = plik.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return (
        f"--- BUYER PERSONA, DO KTÓREJ TEN MATERIAŁ MA TRAFIĆ: {target} ---\n"
        f"{profil}\n\n"
        "Oceń material WZGLĘDEM TEJ KONKRETNEJ OSOBY, nie ogólnie: czy ton, argumenty i "
        "obietnice odpowiadają jej celom, obiekcjom i temu, czego unika (sekcje \"Czego "
        "unika\", \"Obiekcje i bariery\", \"Co ją przekonuje\" powyżej). Niezgodność z tą "
        "personą (zły ton, argumenty dla kogoś innego, ignorowanie jej realnej obiekcji) "
        "jest ZASTRZEŻENIEM BLOKUJĄCYM — opisz WPROST, czego ta persona realnie potrzebuje "
        "zamiast tego, żeby dało się to nanieść jako poprawkę.\n\n"
    )


def _parse_acceptance(text):
    match = re.search(r"akceptacja\s*:\s*(tak|nie)", text, re.IGNORECASE)
    if match:
        return match.group(1).lower() == "tak"
    return False  # brak jednoznacznego "tak" = fail-closed


def _parse_section(text, naglowek, konczace=()):
    """Punkty z jednej sekcji odpowiedzi. Sekcje nie mogą się zlewać, bo lista
    blokujących musi być rozłączna z sugestiami."""
    punkty = []
    in_section = False
    for line in text.splitlines():
        if re.match(naglowek, line, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            if any(re.match(k, line, re.IGNORECASE) for k in konczace):
                break
            stripped = line.strip(" -\t*")
            if stripped and stripped.lower().rstrip(".") != "brak":
                punkty.append(stripped)
    return punkty


def _parse_blocking(text):
    """Zastrzeżenia, które wstrzymują zadanie. Starszy format (samo
    'ZASTRZEŻENIA:') traktujemy jako blokujące — zgodność wstecz."""
    blokujace = _parse_section(text, r"\s*zastrze[żz]enia\s+blokuj[ąa]ce\s*:", (r"\s*sugestie\s*:",))
    if blokujace:
        return blokujace
    return _parse_section(text, r"\s*zastrze[żz]enia\s*:", (r"\s*sugestie\s*:",))


def _parse_suggestions(text):
    """Uwagi wartościowe, ale nieblokujące — idą do komentarza i do rozwoju skilla."""
    return _parse_section(text, r"\s*sugestie\s*:")


# Zachowane pod starą nazwą — używane przez testy i zewnętrzne wywołania.
_parse_concerns = _parse_blocking


def review(task, execution_result, config=None):
    context = load_business_context(task)
    persona = load_persona()
    prompt = build_prompt(task, execution_result, context, persona, load_ustalenia())

    answer = task_thinker.ask_model(prompt, caller="bot_bozena_biznes.review")
    if not answer["available"]:
        return verdict(
            BOT, "skipped", 0.3,
            "Brak modelu do oceny biznesowej — nie potwierdzam odbioru. "
            "(Bożena jest obowiązkowa: bramka eskaluje to do człowieka.)",
            concerns=["Odbiór biznesowy niezweryfikowany (brak modelu)."],
        )

    text = (answer["text"] or "").strip()
    blokujace = _parse_blocking(text)
    sugestie = _parse_suggestions(text)

    # Decyduje BRAK zastrzeżeń blokujących, nie samo słowo "nie". Model przy
    # swobodnej ocenie odrzucał materiał za drobiazg stylistyczny tak samo jak za
    # błąd w liczbie — stąd brały się sprzeczne werdykty między przebiegami.
    if _parse_acceptance(text) or not blokujace:
        szczegol = f"[{answer['source']}] {text}"
        if sugestie and not _parse_acceptance(text):
            szczegol += "\n(Przyjęte mimo uwag — żadna nie jest na liście blokujących.)"
        wynik = verdict(BOT, "approved", 0.8, szczegol)
        wynik["suggestions"] = sugestie
        return wynik

    wynik = verdict(
        BOT, "rejected", 0.8, f"[{answer['source']}] {text}",
        concerns=blokujace,
    )
    wynik["suggestions"] = sugestie
    return wynik
