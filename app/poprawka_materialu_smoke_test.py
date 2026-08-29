"""
Test dymny pętli poprawek — najpierw popraw, potem dopiero angażuj człowieka.
Bez sieci i bez modelu (wołanie modelu wstrzykiwane).

Powód istnienia: wcześniej KAŻDA wada, nawet "brak jednostki przy temperaturze",
kończyła zadanie statusem "wymaga decyzji" i zakładała właścicielowi nowe zadanie.
Agent dokładał pracy zamiast ją zdejmować.

Użycie:
    python poprawka_materialu_smoke_test.py
"""

import sys

import poprawka_materialu
import runner_loop


def _ask(tekst):
    def _f(prompt):
        _f.prompt = prompt
        return {"available": True, "text": tekst, "source": "atrapa", "detail": "OK"}
    return _f


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    ask = _ask("Dziś w Warszawie od 18°C do 24°C, bez opadów.")
    wynik = poprawka_materialu.popraw("Dziś w Warszawie 24 stopnie.",
                                      ["Brak jednostki przy temperaturze.", "Brak temperatury minimalnej."],
                                      zadanie="Pogoda na dziś, dwa zdania", ask=ask)
    checks.append(("Poprawka nanosi uwagi i zwraca sam materiał",
                   wynik["available"] and "18°C" in wynik["material"]))
    checks.append(("Koszt poprawki jest raportowany", isinstance(wynik["cost_usd"], (int, float))))
    checks.append(("Prompt niesie uwagi do naniesienia", "Brak jednostki" in ask.prompt))
    checks.append(("Prompt zakazuje dokładania faktów spoza materiału",
                   "NIE dodawaj faktów" in ask.prompt))

    brak_danych = poprawka_materialu.popraw(
        "Kurs EUR to 4,3165 zł.", ["Brakuje kursu USD."],
        ask=_ask("NIE_DA_SIE_POPRAWIC: w materiale nie ma kursu USD"))
    checks.append(("Gdy uwaga wymaga nowych danych -> poprawka odmawia, nie zmyśla",
                   brak_danych["available"] is False and "USD" in brak_danych["powod"]))
    checks.append(("Odmowa 'brakuje danych' oznaczona flagą, nie zgadywana z tekstu powodu",
                   brak_danych["brak_danych"] is True))

    checks.append(("Brak uwag -> brak poprawki (nie wołamy modelu bez powodu)",
                   poprawka_materialu.popraw("cokolwiek", [], ask=_ask("x"))["available"] is False))
    checks.append(("Pusty materiał -> brak poprawki",
                   poprawka_materialu.popraw("", ["uwaga"], ask=_ask("x"))["available"] is False))

    bez_modelu = poprawka_materialu.popraw(
        "tekst", ["uwaga"],
        ask=lambda p: {"available": False, "text": None, "source": None, "detail": "Brak modelu."})
    checks.append(("Brak modelu -> available=False, bez wyjątku", bez_modelu["available"] is False))
    checks.append(("Awaria modelu to NIE jest diagnoza 'brakuje danych'",
                   bez_modelu["brak_danych"] is False))

    # --- rozpoznanie: wada materiału czy źle postawione zadanie ---
    zle_zadanie = runner_loop._zadanie_zle_postawione(
        {"acceptance_notes": "NIE WYKONANO — wskazane źródło nie zawiera odpowiedzi."},
        {"concerns": ["Brak zamówionego elementu: nie ma kursu."]})
    checks.append(("Brak danych w źródle rozpoznany jako problem ZADANIA", zle_zadanie is True))

    wada_materialu = runner_loop._zadanie_zle_postawione(
        {"acceptance_notes": "Kurs EUR wynosi 4,3165 zł."},
        {"concerns": ["Brak jednostki przy liczbie."]})
    checks.append(("Drobna wada redakcyjna NIE jest problemem zadania", wada_materialu is False))

    jawna_diagnoza = runner_loop._zadanie_zle_postawione(
        {"acceptance_notes": "Raport o braku danych plus szablon do wypełnienia."},
        {"concerns": ["Wynik nie odpowiada zamówieniu."], "zadanie_zle_postawione": True})
    checks.append(("Jawna diagnoza z pętli poprawek bije heurystykę po słowach kluczowych",
                   jawna_diagnoza is True))

    # --- pętla: poprawiony materiał przechodzi bramkę ---
    oryginalna_bramka = runner_loop.bot_gustaw_bramka.run_gate
    oryginalna_poprawka = runner_loop.poprawka_materialu.popraw
    try:
        przebiegi = {"n": 0}

        def _bramka(task, execution_result, config=None):
            przebiegi["n"] += 1
            if "18°C" in (execution_result.get("acceptance_notes") or ""):
                return {"passed": True, "summary": "OK po poprawce", "concerns": []}
            return {"passed": False, "summary": "brak jednostki", "concerns": ["Brak jednostki."]}

        runner_loop.bot_gustaw_bramka.run_gate = _bramka
        runner_loop.poprawka_materialu.popraw = lambda material, uwagi, zadanie="", ask=None: {
            "available": True, "material": "Dziś od 18°C do 24°C.", "cost_usd": 0.001, "powod": ""}

        gate, efekt = runner_loop._popraw_i_sprawdz_ponownie(
            {"task_id": "T-1", "title": "Pogoda"},
            {"acceptance_notes": "Dziś 24 stopnie.", "cost_usd": 0.01},
            {"passed": False, "summary": "brak jednostki", "concerns": ["Brak jednostki."]})
        checks.append(("Po poprawce zadanie przechodzi bramkę bez udziału człowieka", gate["passed"] is True))
        checks.append(("Materiał w wyniku jest ten poprawiony", "18°C" in efekt["acceptance_notes"]))
        checks.append(("Koszt poprawki doliczony do zadania", efekt["cost_usd"] > 0.01))

        # Materiał, którego poprawka nie ratuje — limit prób musi zadziałać.
        przebiegi["n"] = 0
        runner_loop.poprawka_materialu.popraw = lambda material, uwagi, zadanie="", ask=None: {
            "available": True, "material": "Dziś 24 stopnie.", "cost_usd": 0.001, "powod": ""}
        gate, _ = runner_loop._popraw_i_sprawdz_ponownie(
            {"task_id": "T-2", "title": "Pogoda"},
            {"acceptance_notes": "Dziś 24 stopnie.", "cost_usd": 0.0},
            {"passed": False, "summary": "brak jednostki", "concerns": ["Brak jednostki."]})
        checks.append(("Nieskuteczna poprawka nie kręci się w kółko (limit prób)",
                       gate["passed"] is False and przebiegi["n"] <= runner_loop.MAX_POPRAWEK))

        # Poprawka mówi wprost, jakich danych brakuje — to diagnoza ZADANIA i musi
        # dojść do runnera. Wcześniej ginęła w logu, a zadanie szło na eskalację do
        # człowieka z pytaniem, na które nikt nie umiał odpowiedzieć.
        runner_loop.poprawka_materialu.popraw = lambda material, uwagi, zadanie="", ask=None: {
            "available": False, "material": "", "cost_usd": 0.002, "brak_danych": True,
            "powod": "Poprawka redakcyjna nie wystarczy: brakuje estymacji i czasu realnego."}
        gate, _ = runner_loop._popraw_i_sprawdz_ponownie(
            {"task_id": "T-3", "title": "Feedback: Dodanie godzin do aplikacji"},
            {"acceptance_notes": "Raport o braku danych plus szablon.", "cost_usd": 0.0},
            {"passed": False, "summary": "odrzucone", "concerns": ["Wynik nie odpowiada zamówieniu."]})
        checks.append(("Brak danych z poprawki oznacza zadanie jako źle postawione",
                       runner_loop._zadanie_zle_postawione(
                           {"acceptance_notes": "Raport o braku danych plus szablon."}, gate) is True))
        checks.append(("Powód braku danych dopisany do zastrzeżeń (człowiek widzi, czego zabrakło)",
                       any("brakuje estymacji" in c for c in gate["concerns"])))
        checks.append(("Pierwotne zastrzeżenia bramki zachowane",
                       "Wynik nie odpowiada zamówieniu." in gate["concerns"]))
    finally:
        runner_loop.bot_gustaw_bramka.run_gate = oryginalna_bramka
        runner_loop.poprawka_materialu.popraw = oryginalna_poprawka

    komentarz = runner_loop._comment_zamkniete_z_feedbackiem(
        "pawel", {"acceptance_notes": "NIE WYKONANO — brak danych."},
        {"concerns": ["Źródło nie zawiera kursu USD."]})
    checks.append(("Zamknięcie z feedbackiem mówi, czego zabrakło", "USD" in komentarz))
    checks.append(("Zamknięcie z feedbackiem NIE zakłada zadania człowiekowi",
                   "Nie zakładam osobnego zadania" in komentarz))

    print("\n--- Wynik testu dymnego pętli poprawek ---")
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
