"""
Test dymny podziału na zastrzeżenia BLOKUJĄCE i SUGESTIE w odbiorze biznesowym
(Bożena). Bez modelu i bez sieci — odpowiedzi modelu są wstrzykiwane.

Powód istnienia: ten sam materiał bywał raz przyjmowany, raz odrzucany, bo każdy
drobiazg stylistyczny blokował zadanie tak samo jak błąd w liczbie. Ten test
pilnuje reguły: wstrzymuje TYLKO zastrzeżenie blokujące.

Użycie:
    python odbior_ustalenia_smoke_test.py
"""

import sys

import bot_bozena_biznes as bozena

TYLKO_SUGESTIE = """AKCEPTACJA: nie
UZASADNIENIE: Materiał jest poprawny, ale mam uwagi redakcyjne.
ZASTRZEŻENIA BLOKUJĄCE:
- brak
SUGESTIE:
- Zdanie brzmi ciężko, przydałby się lżejszy szyk.
- Warto dodać dynamikę rok do roku."""

BLOKUJACE = """AKCEPTACJA: nie
UZASADNIENIE: Zła data notowania.
ZASTRZEŻENIA BLOKUJĄCE:
- Kurs pochodzi z 19.08, a zadanie dotyczyło 20.08.
SUGESTIE:
- brak"""

STARY_FORMAT = """AKCEPTACJA: nie
UZASADNIENIE: Brak liczby.
ZASTRZEŻENIA:
- Nie ma wartości kursu."""

PRZYJETE = """AKCEPTACJA: tak
UZASADNIENIE: Dokładnie to, o co prosiłam.
ZASTRZEŻENIA BLOKUJĄCE:
- brak
SUGESTIE:
- brak"""


def _ask(tekst):
    return lambda prompt: {"available": True, "text": tekst, "source": "atrapa", "detail": "OK"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    zadanie = {"title": "Kurs EUR", "action_type": "read_report"}
    efekt = {"acceptance_notes": "Kurs średni EUR wynosi 4,3165 zł (tabela 161/A/NBP/2026 z 20.08.2026)."}

    original = bozena.task_thinker.ask_model
    try:
        bozena.task_thinker.ask_model = _ask(TYLKO_SUGESTIE)
        wynik = bozena.review(zadanie, efekt)
        checks.append(("Same sugestie -> zadanie PRZYJĘTE mimo słowa 'nie'", wynik["verdict"] == "approved"))
        checks.append(("Sugestie są zachowane, nie gubione", len(wynik.get("suggestions", [])) == 2))
        checks.append(("Sugestie nie trafiają do zastrzeżeń blokujących", wynik["concerns"] == []))
        checks.append(("Uzasadnienie mówi, że przyjęto mimo uwag", "mimo uwag" in wynik["detail"]))

        bozena.task_thinker.ask_model = _ask(BLOKUJACE)
        wynik = bozena.review(zadanie, efekt)
        checks.append(("Zastrzeżenie blokujące -> ODRZUCENIE", wynik["verdict"] == "rejected"))
        checks.append(("Powód odrzucenia jest konkretny", "19.08" in wynik["concerns"][0]))

        bozena.task_thinker.ask_model = _ask(STARY_FORMAT)
        wynik = bozena.review(zadanie, efekt)
        checks.append(("Starszy format 'ZASTRZEŻENIA:' nadal blokuje (zgodność wstecz)",
                       wynik["verdict"] == "rejected" and wynik["concerns"]))

        bozena.task_thinker.ask_model = _ask(PRZYJETE)
        wynik = bozena.review(zadanie, efekt)
        checks.append(("Czysta akceptacja -> approved bez uwag",
                       wynik["verdict"] == "approved" and wynik["concerns"] == []))

        bozena.task_thinker.ask_model = lambda prompt: {"available": False, "text": None,
                                                        "source": None, "detail": "Brak modelu."}
        wynik = bozena.review(zadanie, efekt)
        checks.append(("Brak modelu -> skipped (fail-closed, bramka eskaluje)", wynik["verdict"] == "skipped"))
    finally:
        bozena.task_thinker.ask_model = original

    ustalenia = bozena.load_ustalenia()
    checks.append(("Plik ustaleń się parsuje i ma obie listy",
                   bool(ustalenia.get("blokujace")) and bool(ustalenia.get("nie_blokuje"))))
    prompt = bozena.build_prompt(zadanie, efekt, {"oczekiwania": "", "na_co_uwaga": []}, "", ustalenia)
    checks.append(("Prompt niesie listę blokujących i rozstrzygnięte kwestie",
                   "WSTRZYMUJE ZADANIE" in prompt and "JUŻ ROZSTRZYGNIĘTE" in prompt))
    checks.append(("Prompt mówi wprost, kiedy wolno odmówić",
                   "TYLKO gdy wskażesz co najmniej jedno zastrzeżenie" in prompt))

    bez_ustalen = bozena.build_prompt(zadanie, efekt, {"oczekiwania": "", "na_co_uwaga": []}, "", {})
    checks.append(("Brak pliku ustaleń nie wywraca oceny (prompt bez sekcji zasad)",
                   "WSTRZYMUJE ZADANIE" not in bez_ustalen))

    print("\n--- Wynik testu dymnego odbioru biznesowego ---")
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
