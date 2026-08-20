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
_GREEN_ACTIONS = {"validate_pbip", "read_report", "capture_screenshot", "fetch_url"}


def _haystack(task):
    parts = [task.get("title", ""), task.get("description", ""),
             task.get("expected_result", ""), task.get("acceptance_criteria", "")]
    return " ".join(p for p in parts if p).lower()


def hint_from_task(task):
    """Zwraca 'green' | 'yellow' | 'red' na podstawie treści i akcji zadania."""
    action = (task.get("action") or "").lower()
    if action in _GREEN_ACTIONS:
        return "green"

    text = _haystack(task)
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
