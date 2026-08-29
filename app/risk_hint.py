"""
Wywnioskowanie koloru ryzyka Z TREŚCI zadania (nie ze sztywnego 'yellow').
Naprawia dziurę: realny Projectly ustawiał każde zadanie na 'yellow' na sztywno
(projectly_client._map_task), więc klasyfikacja ryzyka na produkcji była fikcją —
akcje czerwone (wysyłka, budżet, publikacja, usunięcie) nie były rozpoznawane.

To heurystyka słów kluczowych, celowo KONSERWATYWNA i fail-safe: gdy coś wygląda
na nieodwracalne/zewnętrzne (mail do klienta, zmiana budżetu, publikacja, kasowanie),
podnosimy do 'red' (człowiek decyduje). Czysty odczyt/analiza -> 'green'. W razie
wątpliwości -> 'yellow' (auto w granicach polityki, z walidatorami).

To NIE zastępuje docelowej klasyfikacji po ROZPOZNANEJ AKCJI workera (gdy będą
realni workerzy) — jest bezpiecznym domyślnym hintem, gdy źródło zadania go nie
niesie albo niesie sztywną wartość domyślną.
"""

# Kolejność ma znaczenie: red bije green. Frazy, nie pojedyncze litery.
_RED_KEYWORDS = (
    "wyślij", "wyslij", "wyślę", "wysyłk", "wysylk", "mail do klient", "e-mail do klient",
    "budżet", "budzet", "opublikuj", "publikacj", "publikuj", "usuń", "usun", "skasuj",
    "przelew", "zapłać", "zaplac", "faktur", "wdroż na produkcj", "wdroz na produkcj",
    "deploy", "kampani", "zmień uprawnien", "zmien uprawnien", "nadpisz", "przenieś dane",
)
_GREEN_KEYWORDS = (
    "sprawdź", "sprawdz", "waliduj", "walidacj", "przeczytaj", "odczyt", "przeanalizuj",
    "analiza", "zbadaj", "podgląd", "podglad", "przejrzyj", "zweryfikuj strukturę",
    "raport tylko do odczytu", "wylistuj", "policz",
)
# Akcje workerów, które są z definicji read-only (zielone) niezależnie od tytułu.
# browser_task_readonly = executor.rozpoznaj_narzedzie zwraca to TYLKO gdy
# zadanie nie niesie żadnych browser_steps — bez kroków worker mechanicznie
# nie może kliknąć/wypełnić niczego (sam navigate+screenshot+odczyt tekstu),
# więc słowo "kampania" w treści (żywy przypadek: "sprawdź WYNIKI KAMPANII")
# nie powinno podnosić koloru do red — to ten sam odczyt co fetch_url, inne
# źródło. Zadanie Z krokami (klikanie) zostaje pod zwykłą klasyfikację słów.
_GREEN_ACTIONS = {"validate_pbip", "read_report", "capture_screenshot", "fetch_url",
                  "browser_task_readonly", "mailerlite_report", "zanfia_query", "sharepoint_read"}

# Czasowniki, które opisują CZYNNOŚĆ do wykonania na zewnątrz. Ich obecność
# trzyma zadanie na czerwonym nawet wtedy, gdy rozpoznaliśmy read-only workera —
# bo "zrób zestawienie i wyślij je klientowi" to zadanie, którego worker wykona
# tylko połowę, a zamknięcie go jako zrobione byłoby nieprawdą.
_RED_CZASOWNIKI = (
    "wyślij", "wyslij", "wyślę", "wysle", "roześlij", "rozeslij", "opublikuj", "publikuj",
    "usuń", "usun", "skasuj", "nadpisz", "zapłać", "zaplac", "przelej", "zmień budżet",
    "zmien budzet", "wdroż na produkcj", "wdroz na produkcj", "deploy",
)


def _tekst(wartosc):
    """Pole zadania -> tekst. acceptance_criteria bywa LISTĄ kryteriów (tak
    wygląda w mock_data/sample_tasks.json i tak potrafi przyjść z Projectly),
    a str.join na liście wywracał całą pętlę runnera wyjątkiem TypeError —
    zadanie nie było wtedy ani wykonane, ani eskalowane, tylko przepadało."""
    if isinstance(wartosc, (list, tuple)):
        return " ".join(_tekst(x) for x in wartosc)
    return "" if wartosc is None else str(wartosc)


def _haystack(task):
    parts = [task.get("title", ""), task.get("description", ""),
             task.get("expected_result", ""), task.get("acceptance_criteria", "")]
    return " ".join(_tekst(p) for p in parts if p).lower()


def hint_from_task(task, rozpoznane_narzedzie=None):
    """Zwraca 'green' | 'yellow' | 'red' na podstawie treści i akcji zadania.

    rozpoznane_narzedzie: nazwa narzędzia, którym worker FAKTYCZNIE wykona to
    zadanie (executor.rozpoznaj_narzedzie). Gdy jest podana i narzędzie jest
    z definicji tylko do odczytu, wygrywa nad heurystyką słów — bo wtedy nie
    zgadujemy już, co się stanie, tylko to wiemy. Bez tego 'Zestawienie wysyłek
    kampanii z MailerLite' wpadało na czerwone przez same rzeczowniki 'wysyłk'
    i 'kampani', choć zadanie jest czystym odczytem statystyk — i takie
    zestawienie nie mogłoby nigdy pojechać automatem."""
    text = _haystack(task)

    action = (task.get("action") or "").lower()
    if action in _GREEN_ACTIONS or rozpoznane_narzedzie in _GREEN_ACTIONS:
        # Narzędzie z definicji read-only wygrywa nad heurystyką słów — ALE nie
        # zwraca "green" na skróty: jeśli tytuł/opis zleca też czynność na
        # zewnątrz (_RED_CZASOWNIKI), read-only worker wykona tylko połowę
        # zadania, więc zostaje czerwone (błąd naprawiony 23.08.2026 — wcześniejszy
        # wariant zwracał "green" od razu, zanim ten test się w ogóle wykonał).
        if any(kw in text for kw in _RED_CZASOWNIKI):
            return "red"
        return "green"

    if any(kw in text for kw in _RED_KEYWORDS):
        return "red"
    if any(kw in text for kw in _GREEN_KEYWORDS):
        return "green"
    return "yellow"


if __name__ == "__main__":
    samples = [
        {"title": "Wyślij raport mailem do klienta INDEKA"},
        {"title": "Sprawdź strukturę PBIP i policz strony"},
        {"title": "Przepięcie źródła w raporcie Magnapharm"},
        {"action": "validate_pbip", "title": "cokolwiek"},
    ]
    for s in samples:
        print(f"{hint_from_task(s):6} <- {s.get('title')}")
