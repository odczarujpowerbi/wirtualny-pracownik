"""
Test dymny decyzji podejmowanej po bramce jakości (runner_loop._decyzja_bramki).

Dlaczego osobno: "bramka nie przepuściła" to w rzeczywistości TRZY różne
sytuacje, a mylenie ich kosztowało realne zadania dla człowieka. Wynik czysto
tekstowy (bez zrzutu, testów i powtórki) dostawał zero zgód i zero zastrzeżeń,
więc szedł do właściciela jako zadanie "Wymaga decyzji" z uzasadnieniem
"Zastrzeżenia: brak szczegółów". Po trzech takich zadaniach kacper_monitor
zakładał jeszcze zadanie naprawcze "quality_gate zawodzi powtarzalnie", które
samo trafiało w tę samą ścieżkę: pętla eskalacji bez treści do decyzji.

Uruchamialny lokalnie bez kluczy API (funkcja jest deterministyczna, nie woła
modeli ani Projectly).

Użycie:
    python runner_loop_smoke_test.py
"""

import sys

import runner_loop


def _gate(passed, nothing_to_check=False, concerns=None):
    """Minimalny werdykt bramki w kształcie, jaki zwraca bot_gustaw_bramka.run_gate."""
    return {"passed": passed, "nothing_to_check": nothing_to_check, "concerns": list(concerns or [])}


def test_bramka_przeszla():
    decyzja = runner_loop._decyzja_bramki(_gate(True), {"acceptance_notes": "gotowe"})
    assert decyzja == runner_loop.GATE_PRZESZLO, decyzja
    print("OK  bramka przeszła -> zadanie zamknięte jako wykonane")


def test_nie_bylo_czego_sprawdzic():
    # Wynik tekstowy: wszystkie boty pominięte, zero zastrzeżeń.
    decyzja = runner_loop._decyzja_bramki(
        _gate(False, nothing_to_check=True), {"acceptance_notes": "Odpowiedź tekstowa na pytanie."})
    assert decyzja == runner_loop.GATE_BEZ_WERYFIKACJI, decyzja
    print("OK  brak czego sprawdzić -> BEZ zadania decyzyjnego dla człowieka")


def test_zle_postawione_zadanie():
    decyzja = runner_loop._decyzja_bramki(
        _gate(False, concerns=["Źródło nie zawiera danych za lipiec."]),
        {"acceptance_notes": "Nie wykonano: brak danych."})
    assert decyzja == runner_loop.GATE_ZLE_ZADANIE, decyzja
    print("OK  źle postawione zadanie -> zamknięcie z feedbackiem")


def test_realna_wada_blokuje():
    # Zastrzeżenie merytoryczne MUSI nadal iść do człowieka, inaczej poprawka
    # tej pętli eskalacji przepuszczałaby wadliwe wyniki bez decyzji.
    decyzja = runner_loop._decyzja_bramki(
        _gate(False, concerns=["Model wizyjny ocenił zrzut ekranu jako niepoprawny."]),
        {"acceptance_notes": "Raport z wykresem.", "screenshot_path": "runs/zrzut.png"})
    assert decyzja == runner_loop.GATE_BLOKADA, decyzja
    print("OK  realna wada jakości -> eskalacja do człowieka (bez zmian)")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    test_bramka_przeszla()
    test_nie_bylo_czego_sprawdzic()
    test_zle_postawione_zadanie()
    test_realna_wada_blokuje()
    print("\nWszystkie testy decyzji po bramce przeszły.")
