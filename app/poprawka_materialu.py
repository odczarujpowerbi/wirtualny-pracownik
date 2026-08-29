"""
Poprawka materiału wg zastrzeżeń bramki — pętla, której agentowi brakowało.

Bez niej każda wada, nawet drobna, kończyła zadanie statusem "wymaga decyzji"
i tworzyła właścicielowi nowe zadanie do rozpatrzenia. Agent produkował pracę
zamiast ją zdejmować, a zastrzeżenia bramki były konkretne i nadawały się do
samodzielnego naniesienia ("brak jednostki przy temperaturze", "materiał ma być
w trzech zdaniach", "usuń zdanie o zastosowaniu").

Zasada: poprawiamy TYLKO redakcję materiału na podstawie danych, które już mamy.
Nie dociągamy nowych źródeł i nie dopisujemy faktów — jeśli zastrzeżenie mówi
"brakuje kursu USD", poprawka tego nie naprawi i zadanie ma iść do człowieka.
Dlatego model dostaje jawny zakaz dokładania czegokolwiek spoza materiału.

Bez modelu degraduje się łagodnie (available=False) — wywołujący zostaje przy
dotychczasowej ścieżce eskalacji.

Użycie:
    python poprawka_materialu.py "tresc materialu" "zastrzezenie 1" "zastrzezenie 2"
"""

import sys

import cost_estimator
import env_bootstrap  # noqa: F401 — UTF-8 na stdout (Windows)
import task_thinker

PROMPT = """Popraw poniższy materiał zgodnie z uwagami odbioru. Zwróć WYŁĄCZNIE poprawiony
materiał — bez komentarza, bez wyjaśnień, bez listy zmian.

ZADANIE, którego materiał dotyczy:
{zadanie}

UWAGI DO NANIESIENIA (każda jest powodem, dla którego materiał odrzucono):
{uwagi}

MATERIAŁ DO POPRAWY:
{material}

ZASADY POPRAWKI:
- Nanieś dokładnie to, o co proszą uwagi. Nic więcej nie zmieniaj.
- NIE dodawaj faktów, liczb ani cech, których nie ma w materiale. Jeśli uwaga wymaga
  danych, których tu nie ma (np. brakującego kursu innej waluty), zwróć jedną linię:
  NIE_DA_SIE_POPRAWIC: <czego brakuje>
- Nie dopisuj źródła, daty pobrania ani żadnej stopki.
- Nie pisz nic do zlecającego. To materiał dla odbiorcy końcowego.
- Zachowaj język polski i formę zamówioną w zadaniu."""


def popraw(material, uwagi, zadanie="", ask=None):
    """Zwraca {available, material, cost_usd, powod, brak_danych}. Nigdy nie rzuca.

    available=False oznacza: nie da się poprawić samą redakcją (albo brak modelu) —
    wtedy wywołujący eskaluje jak dotąd.

    brak_danych=True to węższy przypadek: model odpowiedział NIE_DA_SIE_POPRAWIC,
    czyli stwierdził wprost, że uwaga wymaga danych, których w materiale nie ma.
    To diagnoza ZADANIA, nie materiału, i wywołujący ma ją odróżnić od awarii
    modelu (bez tego runner eskalował do człowieka zadanie, o którym już wiedział,
    że jest źle postawione — żywy incydent "Feedback: Feedback: Dodanie godzin
    do aplikacji")."""
    # Domyślne "ask" chowa poziom modelu (low — nanoszenie konkretnej listy
    # zastrzeżeń jest z definicji mechaniczne), zamiast wymagać go w publicznej
    # sygnaturze popraw() — tak nikt przez pomyłkę nie wywoła tego na wysokim poziomie.
    ask = ask or (lambda p: task_thinker.ask_model(p, caller="poprawka_materialu.popraw"))
    material = (material or "").strip()
    uwagi = [u for u in (uwagi or []) if str(u).strip()]
    if not material or not uwagi:
        return {"available": False, "material": "", "cost_usd": 0.0, "brak_danych": False,
                "powod": "Brak materiału albo brak konkretnych uwag do naniesienia."}

    prompt = PROMPT.format(zadanie=zadanie or "(brak opisu zadania)",
                           uwagi="\n".join(f"- {u}" for u in uwagi),
                           material=material)
    try:
        wynik = ask(prompt)
    except Exception as exc:  # noqa: BLE001 — brak modelu nie może wywalić pętli
        return {"available": False, "material": "", "cost_usd": 0.0, "brak_danych": False,
                "powod": f"Wywołanie modelu nie powiodło się: {type(exc).__name__}: {exc}"}

    if not wynik or not wynik.get("available"):
        return {"available": False, "material": "", "cost_usd": 0.0, "brak_danych": False,
                "powod": (wynik or {}).get("detail", "Model niedostępny.")}

    tekst = (wynik.get("text") or "").strip()
    koszt = cost_estimator.estimate_call(wynik.get("source") or "claude_code",
                                         input_chars=len(prompt), output_chars=len(tekst))
    if tekst.startswith("NIE_DA_SIE_POPRAWIC"):
        powod = tekst.split(":", 1)[1].strip() if ":" in tekst else tekst
        return {"available": False, "material": "", "cost_usd": koszt, "brak_danych": True,
                "powod": f"Poprawka redakcyjna nie wystarczy: {powod}"}

    if not tekst:
        return {"available": False, "material": "", "cost_usd": koszt, "brak_danych": False,
                "powod": "Model zwrócił pustą poprawkę."}

    return {"available": True, "material": tekst, "cost_usd": koszt, "brak_danych": False, "powod": ""}


def main():
    if len(sys.argv) < 3:
        print("Użycie: python poprawka_materialu.py <materiał> <uwaga> [uwaga...]")
        return 1
    wynik = popraw(sys.argv[1], sys.argv[2:])
    print(wynik["material"] if wynik["available"] else f"[nie poprawiono] {wynik['powod']}")
    return 0 if wynik["available"] else 1


if __name__ == "__main__":
    sys.exit(main())
