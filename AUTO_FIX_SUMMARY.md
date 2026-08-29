# Naprawa: zadania feedbackowe bez danych szły na eskalację do człowieka

## Co się zepsuło

Zadanie `Feedback: Feedback: Dodanie godzin do aplikacji` skończyło się
eskalacją do człowieka (`escalated_to_human`, status `needs_approval`).
Z dziennika zdarzeń widać cały łańcuch:

1. `Cel: None`, `Kryteria akceptacji: None` (zadanie utworzone bez `goal`/`effect`).
2. Wykonanie: agent nie miał ani jednej liczby, więc oddał raport o braku danych
   plus szablon do wypełnienia.
3. Bramka jakości: `content=rejected`, zastrzeżenie "wynik to raport o braku danych".
4. `poprawka_nieudana`: "brakuje danych o rzeczywistym czasie realizacji, estymacji,
   napotkanych trudnościach oraz otwartych zaległościach".
5. Mimo tej diagnozy zadanie poszło na eskalację do człowieka.

Podwojony prefiks w tytule to dowód rekurencji: prośba o feedback do zadania,
które samo było prośbą o feedback.

## Co naprawiono

### 1. `app/task_feedback_requester.py` (źródło niewykonalnego zadania)

- **Rekurencja.** Nowe `is_feedback_task()` odsiewa zadania feedbackowe w
  `find_tasks_needing_feedback()`. Bez tego każde zamknięte zadanie feedbackowe
  rodziło kolejne (`Feedback: Feedback: ...`), coraz bardziej bez treści.
- **Pusty opis.** Nowe `build_feedback_brief()` wstawia do opisu dane, które
  `projectly_client._map_task` i tak już zwraca, a które były wyrzucane:
  wykonawca, estymacja, czas realny, wyliczone odchylenie (`format_deviation()`),
  termin, data zamknięcia. Brakujące pola są nazwane wprost jako
  `(brak w Projectly)`, nie zmyślane.
- **Brak celu i kryteriów odbioru.** `create_task()` dostaje teraz
  `expected_result` i `acceptance_criteria`. Docstring `projectly_client.create_task`
  ostrzega wprost, że bez nich bramka ocenia efekt względem pustego oczekiwania
  i daje fałszywie negatywne werdykty. Dokładnie to się stało.
  Kryterium 4 mówi jasno, że jeśli czegoś wie tylko wykonawca, poprawną
  odpowiedzią jest napisanie wprost, czego brakuje.
- **Cichy błąd przypisania.** `task.get("assignee", "unassigned_pool")` nigdy nie
  zwracał wartości domyślnej, bo `_map_task` zawsze ustawia klucz `assignee`
  (przy braku przypisania na `None`). Zamienione na `task.get("assignee") or "unassigned_pool"`.

### 2. `app/poprawka_materialu.py` + `app/runner_loop.py` (zgubiona diagnoza)

- `popraw()` zwraca dodatkowe pole `brak_danych`. `True` tylko wtedy, gdy model
  odpowiedział `NIE_DA_SIE_POPRAWIC`, czyli stwierdził, że uwaga wymaga danych
  spoza materiału. Odróżnia to diagnozę zadania od zwykłej awarii modelu, które
  wcześniej były nierozróżnialne (oba: `available=False`).
- `_popraw_i_sprawdz_ponownie()` przy `brak_danych=True` dopisuje powód do
  `gate["concerns"]` i oznacza bramkę flagą `zadanie_zle_postawione`.
- `_zadanie_zle_postawione()` honoruje tę flagę przed heurystyką po słowach kluczowych.

Efekt: zadanie, o którym agent już wie, że jest źle postawione, idzie ścieżką
`zamkniete_z_feedbackiem` (zamknięte z konkretną listą "czego zabrakło"), zamiast
zakładać człowiekowi zadanie z pytaniem, na które nikt nie odpowie. To jest ta
sama zasada, którą kod deklaruje w `_comment_zamkniete_z_feedbackiem`:
"Agent ma zdejmować pracę, nie dokładać jej."

## Jak to zweryfikować

```
cd app
python task_feedback_requester_smoke_test.py
python poprawka_materialu_smoke_test.py
python self_check.py
```

`task_feedback_requester_smoke_test.py` to nowy plik (atrapa klienta Projectly,
bez sieci, `send_email=False`). Pokrywa: odsiewanie zadań feedbackowych,
liczenie odchylenia (w tym brak jednej z liczb), zawartość briefu, obecność
celu i kryteriów odbioru w utworzonym zadaniu, pojedynczy prefiks w tytule oraz
fallback przypisania.

`poprawka_materialu_smoke_test.py` dostał cztery nowe asercje: flaga
`brak_danych` przy `NIE_DA_SIE_POPRAWIC`, jej brak przy awarii modelu,
pierwszeństwo jawnej diagnozy w `_zadanie_zle_postawione` oraz propagacja powodu
do zastrzeżeń bramki (z zachowaniem zastrzeżeń pierwotnych). Istniejące asercje
nie były zmieniane ani osłabiane.

`self_check.py` wykrywa testy dymne globem `*_smoke_test.py`, więc nowy plik
jest w nim automatycznie.

## Czego NIE zweryfikowano

Testów nie udało się uruchomić w tym środowisku: sandbox tej sesji przepuszcza
tylko `python --version`, każde inne wywołanie Pythona (łącznie z
`python -m py_compile`) wymaga ręcznej zgody, a sesja jest nieinteraktywna.
Zmiany przeszły wyłącznie review, bez wykonania. Uruchom trzy komendy powyżej
przed scaleniem.
