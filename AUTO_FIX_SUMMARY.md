# Prośba o feedback nie jest już zadaniem dla bota (koniec pętli "Feedback: Feedback: ...")

## Co się stało

Zadanie `cmtab0y5w09d9x819ktki36wx` — **"Feedback: Feedback: Odpowiedzi na maile od Oli"** —
przeszło pełną ścieżkę wykonania (klasyfikacja, myślenie, worker; 0,20 USD) i skończyło się
eskalacją do człowieka. Model orzekł słusznie: *"Plan nie odpowiada zadaniu"*, i sam zwrócił
uwagę na zapętlony prefiks feedbacku.

Podwójny prefiks w tytule to nie przypadek, tylko ślad pętli w kodzie.

## Przyczyna (dwa błędy w jednym przepływie)

1. **`task_feedback_requester.find_tasks_needing_feedback` brał KAŻDE domknięte zadanie**,
   również prośby o feedback, które sam wcześniej założył (`title=f"Feedback: {title}"`).
   Każde domknięcie dokładało więc kolejny poziom zagnieżdżenia, bez końca.
2. **Prośba o feedback była zakładana na koncie assignee zadania źródłowego**
   (`assigned_to=task.get("assignee")`). Gdy zadanie wykonał bot, assignee to konto AI, więc
   prośba lądowała ze statusem `todo` na koncie AI — a `runner_loop` bierze z Projectly
   wszystko, co ma `todo` na koncie AI, i traktuje jak pracę do wykonania. Pytanie *"ile
   realnie zajęło, co było trudne"* jest adresowane do CZŁOWIEKA i agent nie ma jak go
   wykonać, więc kończyło się eskalacją.

Pętla domykała się sama: prośba trafiała do kolejki bota → bot ją domykał → requester widział
kolejne domknięte zadanie → zakładał "Feedback: Feedback: ...".

## Co zmienione

**`app/feedback_task.py` (nowy)** — wspólne rozpoznanie "to jest prośba o feedback".
Rozpoznanie jest celowo wąskie: znacznik maszynowy `[auto:prosba-o-feedback]` w opisie, albo
prefiks tytułu **razem z** treścią pytania (dla zadań sprzed znacznika). Sam prefiks
`"Feedback: "` nie wystarcza — człowiek ma prawo tak zatytułować własne, prawdziwe zadanie.

**`app/task_feedback_requester.py`** — dwa wykluczenia w `find_tasks_needing_feedback`:
- prośba o feedback sama nie dostaje prośby o feedback (koniec zagnieżdżania),
- pomijamy zadania wykonane przez konto AI. Nic nie tracimy: samoocenę ze swojej pracy agent
  zapisuje i tak w polu `feedback` zadania źródłowego (`runner_loop._zapisz_feedback`).

Zakładane prośby niosą teraz znacznik maszynowy w opisie.

**`app/runner_loop.py`** — runner rozpoznaje prośbę o feedback i domyka ją bez modelu, bez
workera i bez eskalacji, z komentarzem wyjaśniającym, gdzie jest samoocena agenta. To dotyczy
próśb, które w kolejce **już leżą** (naprawa requestera działa dopiero na nowe). Guard stoi
PO sprawdzeniu bezpieczeństwa promptu, żeby podejrzana treść nadal eskalowała.

## Jak zweryfikować

```
cd app
python feedback_task_smoke_test.py     # nowy test dymny (wpina się sam w self_check.py)
python self_check.py                   # cała regresja
```

Test dymny pokrywa: rozpoznanie prośby (ze znacznikiem, sprzed znacznika, zapętlonej), brak
fałszywego trafienia na zadaniu człowieka pod tytułem "Feedback: ...", oba wykluczenia
w `find_tasks_needing_feedback`, brak drugiej rundy po domknięciu prośby, oraz zachowanie
runnera na oryginalnym zadaniu `cmtab0y5w09d9x819ktki36wx` (status `done`, zero eskalacji,
model i worker podmienione na atrapy, które rzucają wyjątek, gdyby zostały wywołane).

**Uwaga: testów nie udało się uruchomić w tym środowisku** — sandbox agenta naprawczego
blokuje wywołanie `python` (każda próba kończyła się "This command requires approval").
Zmiany zweryfikowane przeglądem kodu; testy trzeba odpalić przed scaleniem.

## Efekt

- Nie powstają już zadania "Feedback: Feedback: ..." (ani głębsze poziomy).
- Prośby o feedback nie trafiają do kolejki roboczej bota.
- Prośby, które już w tej kolejce są, domykają się za darmo, bez wybudzania człowieka.
