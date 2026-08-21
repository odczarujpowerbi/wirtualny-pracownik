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
    # **kw łapie caller= — review() woła ask_model z caller="bot_bozena_biznes.review"
    # (model_registry, tabela tier), atrapa nie musi go rozróżniać, tylko przyjąć.
    return lambda prompt, **kw: {"available": True, "text": tekst, "source": "atrapa", "detail": "OK"}


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

        bozena.task_thinker.ask_model = lambda prompt, **kw: {"available": False, "text": None,
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

    # --- ocena względem buyer persony (nie generyczne "czy JA bym to wzięła") ---
    # Realna uwaga właściciela: Bożena ma sprawdzać, czy material trafia w
    # DEKLAROWANĄ personę, nie oceniać materiał w oderwaniu od odbiorcy.
    dopisek_kasia = bozena._dopisek_o_personie({"target_persona": "Kasia", "persona_brand": "odczaruj"})
    checks.append(("Persona: profil trafia do promptu, gdy execution_result go niesie",
                   "BUYER PERSONA" in dopisek_kasia and "Kasia" in dopisek_kasia))
    checks.append(("Persona: prompt niesie realną treść profilu (obiekcje/cele), nie samo imię",
                   "Obiekcje i bariery" in dopisek_kasia))
    checks.append(("Persona: niezgodność z personą jest nazwana ZASTRZEŻENIEM BLOKUJĄCYM",
                   "BLOKUJĄCYM" in dopisek_kasia))

    # Dwie marki mają personę o imieniu "Tomek" — bez marki dopasowanie byłoby
    # niebezpieczne (mogłoby ocenić względem profilu z DRUGIEJ marki).
    tomek_odczaruj = bozena._dopisek_o_personie({"target_persona": "Tomek", "persona_brand": "odczaruj"})
    tomek_clickless = bozena._dopisek_o_personie({"target_persona": "Tomek", "persona_brand": "clickless"})
    checks.append(("Persona: 'Tomek' z Odczaruj i z Clickless to DWA różne profile",
                   tomek_odczaruj != tomek_clickless
                   and "analityk" in tomek_odczaruj.lower() and "sceptyk" in tomek_clickless.lower()))
    checks.append(("Persona: bez znanej marki -> brak dopisku (fail-closed, nie zgadujemy)",
                   bozena._dopisek_o_personie({"target_persona": "Tomek"}) == ""))
    checks.append(("Persona: brak target_persona w execution_result -> brak dopisku",
                   bozena._dopisek_o_personie({}) == ""))
    checks.append(("Persona: nieznane imię -> brak dopisku, nie wyjątek",
                   bozena._dopisek_o_personie({"target_persona": "Zenobia", "persona_brand": "odczaruj"}) == ""))

    prompt_z_persona = bozena.build_prompt(
        {"title": "Reklama kursu"}, {"acceptance_notes": "tekst", "target_persona": "Kasia", "persona_brand": "odczaruj"},
        {"oczekiwania": "", "na_co_uwaga": []}, "", {})
    checks.append(("Persona: dopisek trafia do finalnego promptu build_prompt", "BUYER PERSONA" in prompt_z_persona))

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
