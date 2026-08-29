# Naprawa: pętla "Feedback: Feedback: ..." w task_feedback_requester

## Co się stało

Zadanie `Feedback: Feedback: Wymaga decyzji: Ustalenie źródła danych i zakresu
inwentaryzacji SharePoint` poszło do wykonania, bramka jakości je odrzuciła
(dwa razy) i skończyło jako eskalacja do człowieka.

Sam tytuł pokazuje przyczynę. To trzecie ogniwo łańcucha, który mechanizm
wygenerował sam sobie:

1. zadanie merytoryczne → `escalation.escalate_to_human` zakłada
   `Wymaga decyzji: <tytuł>`,
2. po zamknięciu tej eskalacji `task_feedback_requester` zakłada
   `Feedback: Wymaga decyzji: <tytuł>`,
3. po zamknięciu tego zadania — `Feedback: Feedback: Wymaga decyzji: <tytuł>`.

`find_tasks_needing_feedback()` brało KAŻDE zadanie ze statusem `done`, w tym
zadania założone przez sam mechanizm. Plik `runs/feedback_requested.json`
chronił tylko przed powtórnym pytaniem o TO SAMO id — a każde nowe zadanie
feedbackowe ma nowe id, więc licznik nigdy się nie zatrzymywał. Bramka
odrzucała wynik słusznie: do artefaktu procesu (eskalacji, prośby o feedback)
nie da się rzetelnie napisać "ile zajęło i co było trudne".

## Co zmienione

- **`app/task_titles.py`** (nowy): jedno miejsce z prefiksami zadań zakładanych
  przez mechanizm (`Wymaga decyzji:`, `Kontynuacja:`, `Feedback:`),
  `is_auto_generated_title()` do ich rozpoznawania i `derived_title()`, który
  nie nakłada tego samego prefiksu drugi raz.
- **`app/task_feedback_requester.py`**: `find_tasks_needing_feedback()` pomija
  zadania pochodne mechanizmu — to zamyka pętlę. Przy okazji:
  `task.get("assignee", "unassigned_pool")` nie działało dla zadań bez
  przypisania (kontrakt niesie klucz `assignee` z wartością `None`, więc
  wartość domyślna nigdy się nie włączała i zadanie feedbackowe szło z
  `assigned_to=None`) — teraz `task.get("assignee") or "unassigned_pool"`.
  `run_feedback_requests()` przyjmuje `asked_path` (testowalność stanu).
- **`app/escalation.py`**: tytuły eskalacji i kontynuacji budowane przez
  `derived_title()` z tych samych stałych, żeby prefiksy nie rozjechały się z
  filtrem i nie nakładały się kaskadowo.
- **`app/task_feedback_requester_smoke_test.py`** (nowy): test dymny.
- **`app/README.md`**: opis modułu i nowego pliku.

Żadnego pliku nie usunięto ani nie zmieniono zachowania dla zwykłych zadań:
zamknięte zadanie merytoryczne nadal dostaje komentarz, zadanie feedbackowe i
mail, dokładnie raz.

## Jak to zweryfikować

```
cd app
python task_feedback_requester_smoke_test.py   # nowy test
python self_check.py                           # wszystkie testy dymne
```

Test sprawdza, że z listy zamkniętych zadań (`zwykłe`, `Feedback: ...`,
`Wymaga decyzji: ...`, `Kontynuacja: ...`) pytanie o feedback dostaje wyłącznie
zadanie merytoryczne, że drugi przebieg nie pyta ponownie i że zadanie bez
`assignee` trafia do `unassigned_pool`, a nie do `None`.

**Uwaga o weryfikacji:** w tej sesji uruchomienie Pythona było zablokowane przez
uprawnienia narzędzia (`This command requires approval`), więc powyższych
poleceń NIE udało się wykonać. Zmiany zweryfikowane statycznie (przegląd
kontraktów wywołań `client.create_task`/`list_tasks`, sygnatur i importów) —
przed scaleniem uruchom `self_check.py`.
