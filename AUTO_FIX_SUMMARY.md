# Naprawa: zadanie feedbackowe bez danych i pętla „Feedback: Feedback: ...”

## Co się zepsuło

Zadanie **„Feedback: Feedback: Analiza rozmów 1:1 czerwiec i wdrożenie zmian”** (cel: `None`,
kryteria akceptacji: `None`) przeszło klasyfikację jako zielone `read_report`, zostało wykonane,
a potem bramka jakości je odrzuciła (`content=rejected`) i sprawa poszła do człowieka.

Uzasadnienie decyzji było trafne i wskazuje wprost na źródło:

> brakuje danych o realnym czasie wykonania, estymacji, trudnościach merytorycznych i zaległościach
> zadania (...) — bez tych danych nie da się napisać feedbacku, który nie byłby zmyślony.

Sam tytuł z podwójnym „Feedback:” zdradza drugą część problemu.

## Przyczyny w kodzie (`app/task_feedback_requester.py`)

1. **Pętla feedbacku.** `find_tasks_needing_feedback()` brał każde zadanie ze statusem `done`.
   Zadanie feedbackowe utworzone przez ten sam skrypt też jest zadaniem — po jego domknięciu
   dostawało własne zadanie feedbackowe. Stąd `Feedback: Feedback: ...` (i przy kolejnych
   przebiegach rosłoby dalej).
2. **Zadanie feedbackowe nie niosło żadnych danych.** `description` było równe generycznemu
   pytaniu `FEEDBACK_COMMENT`. Zadanie trafiało do osobnej kolejki (przy braku assignee do puli,
   czyli do agenta), gdzie nie ma dostępu do zadania rodzica. Wykonawca miał odpowiedzieć o
   estymacji i czasie realnym, nie mając ani jednej liczby. Zostawały dwa wyjścia: zmyślić albo
   zostać odrzuconym.
3. **Brak celu i kryteriów akceptacji.** `create_task()` było wołane bez `expected_result` /
   `acceptance_criteria` — a jego własny docstring ostrzega, że bez tego bramka jakości ocenia
   efekt względem pustego oczekiwania i daje niespójne, czasem fałszywie negatywne werdykty.
   W dzienniku zadania widać to jako `Cel: None`, `Kryteria akceptacji: None`.
4. **Drobne, ta sama rodzina błędu:** `task.get("assignee", "unassigned_pool")` nigdy nie zwracało
   wartości domyślnej, bo realny klient zawsze zwraca klucz `assignee` (z `None` przy braku
   przypisania). W ścieżce mailowej dawało to adres `None@wewnetrzny`.

## Co zostało zmienione

`app/task_feedback_requester.py`:

- `is_feedback_task()` + filtr w `find_tasks_needing_feedback()` — o prośbę o feedback nie prosimy
  o feedback. Koniec łańcucha `Feedback: Feedback: ...`.
- `build_feedback_request_description()` — opis nowego zadania niesie fakty z zadania źródłowego:
  id, osoba, termin, estymacja, czas realny (`actualHours`), data domknięcia, dotychczasowy
  `feedback` oraz ostatnie komentarze z wątku (jedyne źródło „co było trudne”). Komentarze
  pobierane są PRZED wysłaniem pytania, żeby brief nie cytował własnego pytania bota.
  Czyta zarówno `estimated_hours` (kontrakt realnego klienta), jak i `estimatedHours` (kształt
  mocka/Projectly).
- Braki nazywane wprost („nie zarejestrowano”) i kryteria akceptacji, które taką uczciwą
  odpowiedź uznają za poprawną, a zmyślonych godzin — nie. Zadanie dostaje też `goal`/`effect`,
  więc bramka jakości ma wobec czego oceniać.
- `assigned_to` i adresat maila liczone przez `or`, nie przez domyślną wartość `.get()`.

Nowy `app/task_feedback_requester_smoke_test.py` (moduł nie miał testu dymnego; `self_check.py`
wykrywa go automatycznie po wzorcu `*_smoke_test.py`). 20 asercji, klient Projectly podstawiony
(fake), zero sieci i zero zapisu do plików mocka. Pokrywa: filtrowanie zadań feedbackowych,
obecność danych źródłowych w opisie, obecność celu i kryteriów, powiązanie `kontynuacja` z
rodzicem, oraz ścieżkę „brak danych” (nazwana wprost, żadnego `None` w opisie, przypisanie do puli).

## Jak zweryfikować

```
cd app
python task_feedback_requester_smoke_test.py   # oczekiwane: "Wszystkie testy przeszły."
python self_check.py                            # wszystkie testy dymne repo
```

**Uwaga o weryfikacji:** w sandboksie tego przebiegu uruchamianie Pythona było zablokowane przez
politykę uprawnień (przechodziło wyłącznie `python --version`), więc **testów nie udało się tu
wykonać** — zmiany przeszły przegląd ręczny, ale wynik powyższych komend trzeba potwierdzić
lokalnie przed scaleniem.

Zachowanie w Projectly po naprawie: skrypt jest domyślnie wyłączony w
`config/schedule.default.yaml` (tworzy zadania i wysyła maile), więc weryfikacja na żywo wymaga
ręcznego `python task_feedback_requester.py`.

## Czego świadomie nie ruszono

Eskalacja do człowieka w tym konkretnym przebiegu była **poprawną reakcją** — agent nie miał
danych i nie powinien był ich zmyślić. Naprawa dotyczy miejsca, w którym powstało zadanie bez
danych, a nie bramki jakości ani pętli runnera. Żaden plik nie został usunięty.
