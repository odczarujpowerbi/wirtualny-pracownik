"""
Bożena — odbiór biznesowy.

Funkcja: wciela się w biurowego użytkownika biznesowego po stronie klienta i
ocenia, czy efekt zadania to NA PEWNO to, czego oczekiwał — wg jego wiedzy
biznesowej i kryteriów akceptacji, a nie tylko "czy technicznie działa". To
ostatni głos przed człowiekiem: jeśli Bożena nie powie "tak", zadanie nie idzie
dalej jako gotowe (Bożena jest botem obowiązkowym w bramce — patrz
config/validation_gate.yaml).

Skąd bierze wiedzę (składane od ogólnej do szczegółowej):
- persona biznesowa (personas/bozena_biznes.md) — ton i pryzmat oceny,
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

import task_thinker
from bot_common import verdict

BOT = "bozena"

CONTEXT_PATH = Path(__file__).parent / "config" / "business_context.yaml"
PERSONA_PATH = Path(__file__).parent / "personas" / "bozena_biznes.md"


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


def build_prompt(task, execution_result, context, persona):
    uwagi = "\n".join(f"- {u}" for u in context["na_co_uwaga"]) or "- (brak dodatkowych)"
    return (
        f"{persona}\n\n"
        "--- KONTEKST BIZNESOWY (czego oczekuje użytkownik) ---\n"
        f"{context['oczekiwania']}\n"
        f"Na co zwrócić szczególną uwagę:\n{uwagi}\n\n"
        "--- ZADANIE ---\n"
        f"Tytuł: {task.get('title')}\n"
        f"Oczekiwany rezultat: {task.get('expected_result')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria')}\n\n"
        "--- CO BOT WYKONAŁ (efekt do oceny) ---\n"
        f"{execution_result.get('acceptance_notes') or execution_result.get('output') or '(brak opisu efektu)'}\n\n"
        f"{_dopisek_o_zrodlach(execution_result)}"
        "Oceń, czy to jest efekt, jakiego oczekiwałby użytkownik biznesowy. "
        "Odpowiedz w formacie z persony (AKCEPTACJA / UZASADNIENIE / ZASTRZEŻENIA)."
    )


def _dopisek_o_zrodlach(execution_result):
    """Pochodzenie danych system dokleja POZA materiałem (osobne pole komentarza),
    więc bez tej informacji odbiór biznesowy zarzucał brak źródeł, których po prostu
    nie widział — i odrzucał poprawny efekt. Pokazujemy je wprost, z zaznaczeniem,
    że nie są częścią materiału i nie trzeba ich powtarzać w treści."""
    zrodla = execution_result.get("source_note")
    if not zrodla:
        return ""
    return ("--- POCHODZENIE DANYCH (system dołącza je do zadania automatycznie; NIE są częścią "
            "materiału dla odbiorcy, więc nie wymagaj powtórzenia ich w treści) ---\n"
            f"{zrodla}\n\n")


def _parse_acceptance(text):
    match = re.search(r"akceptacja\s*:\s*(tak|nie)", text, re.IGNORECASE)
    if match:
        return match.group(1).lower() == "tak"
    return False  # brak jednoznacznego "tak" = fail-closed


def _parse_concerns(text):
    concerns = []
    in_section = False
    for line in text.splitlines():
        if re.match(r"\s*zastrze[żz]enia\s*:", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section:
            stripped = line.strip(" -\t")
            if stripped and stripped.lower() != "brak":
                concerns.append(stripped)
    return concerns


def review(task, execution_result, config=None):
    context = load_business_context(task)
    persona = load_persona()
    prompt = build_prompt(task, execution_result, context, persona)

    answer = task_thinker.ask_model(prompt)
    if not answer["available"]:
        return verdict(
            BOT, "skipped", 0.3,
            "Brak modelu do oceny biznesowej — nie potwierdzam odbioru. "
            "(Bożena jest obowiązkowa: bramka eskaluje to do człowieka.)",
            concerns=["Odbiór biznesowy niezweryfikowany (brak modelu)."],
        )

    text = (answer["text"] or "").strip()
    if _parse_acceptance(text):
        return verdict(BOT, "approved", 0.8, f"[{answer['source']}] {text}")

    return verdict(
        BOT, "rejected", 0.8, f"[{answer['source']}] {text}",
        concerns=_parse_concerns(text) or ["Użytkownik biznesowy nie zaakceptowałby tego efektu."],
    )
