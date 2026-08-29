# Naprawa: runner zapętlał się na własnym zadaniu eskalacyjnym

## Co się działo

Dziennik zadania „Wymaga decyzji: Alert: stan maszyny wymaga sprawdzenia” pokazuje
ten sam wzorzec powtórzony osiem razy: `block_closed: needs_approval`, a obok
(z bota monitorującego Projectly) `escalation_task_skipped`.

To zadanie NIE jest pracą do wykonania. Powstało w `escalation.escalate_to_human()`
jako prośba o decyzję człowieka po alercie z `system_health_monitor.py`. Potrafi
jednak wrócić do kolejki agenta: gdy `ProjectlyClient._resolve_person_id()` nie
rozwiąże przypisania na konkretną osobę, `create_task` idzie z `assigneeIds: []`,
a Projectly przypisuje zadanie wg tokenu, czyli do konta AI (udokumentowane wprost
w `app/config/projectly.yaml`, `people_aliases.unassigned_pool`).

`runner_loop.process_task()` nie miał żadnej bramki na taki przypadek i traktował
je jak zwykłe zadanie: wołał model (`task_thinker`), puszczał przez bramkę jakości,
nie miał z czego zbudować wyniku, więc **eskalował je jeszcze raz** i zamykał jako
`needs_approval`. Cykl po cyklu. Efekt: koszt modelu bez żadnej wartości, lawina
komentarzy pod zadaniem, na które i tak czeka człowiek, i kolejne zadania
eskalacyjne w Projectly. Bot monitorujący Projectly ma taką bramkę
(`escalation_task_skipped`) — ten repozytorium jej nie miało.

## Co zmieniono

- `app/escalation.py` — stałe `ESCALATION_TITLE_PREFIX`, `ESCALATION_MARKER`,
  `ESCALATION_SKIP_REASON` oraz funkcja `is_escalation_task(task)`. Rozpoznanie
  po znaczniku `[eskalacja-dla-czlowieka]` w opisie (zadania zakładane od teraz)
  ALBO po przedrostku tytułu „Wymaga decyzji: ” (zadania już leżące w Projectly,
  w tym to, które zapętliło runner). `escalate_to_human()` dokłada znacznik do
  opisu i buduje tytuł z tej samej stałej, żeby jedno nie odjechało od drugiego.
  Zadania „Kontynuacja: …” (`continuation_task_creator`) to praca DLA BOTA i
  celowo nie są łapane.
- `app/runner_loop.py` — `process_task()` na wejściu odkłada zadanie eskalacyjne
  (`_odloz_zadanie_eskalacyjne`): status wewnętrzny `waiting_for_human`, zero
  wywołań modelu, zero bramki, zero komentarzy i zero zmian statusu w Projectly.
  Zdarzenie `escalation_task_skipped` zapisywane RAZ na zadanie, nie co cykl
  pollowania (inaczej zadanie czekające tydzień na decyzję zasypałoby wspólny
  dziennik, który czyta `kacper_monitor`).
- `app/escalation_guard_smoke_test.py` — nowy test dymny (wpina się sam w
  `self_check.py`): rozpoznawanie eskalacji vs zwykłe zadanie vs kontynuacja,
  znakowanie opisu przez `escalate_to_human`, odłożenie bez dotknięcia klienta
  Projectly i bez `block_closed`, brak dublowania wpisu przy pięciu kolejnych
  pollowaniach.
- `app/dashboard.html`, `app/README.md` — etykieta nowego zdarzenia w panelu
  operatora i wpis o naprawie w stanie kodu.

Status `waiting_for_human` jest celowo inny niż `needs_approval`: tamten znaczy
„agent wykonał, czeka na akceptację wyniku”, a tutaj agent nic nie wykonał.
Nie mapujemy go na status Projectly, bo zadania eskalacyjnego w ogóle nie dotykamy.

## Jak zweryfikować

```
cd app
python escalation_guard_smoke_test.py     # nowy test dymny
python self_check.py                      # cała bateria testów dymnych
```

Na żywo: po wpuszczeniu do kolejki zadania z tytułem zaczynającym się od
„Wymaga decyzji: ” runner ma je pominąć — w dashboardzie (`python dashboard.py`)
pojawi się jeden wpis „eskalacja: czeka na człowieka”, bez `analiza (model)`,
bez `bramka jakości` i bez kolejnego zadania eskalacyjnego w Projectly.

**Uwaga:** w środowisku, w którym powstała ta poprawka, uruchomienie interpretera
Pythona było zablokowane, więc powyższych testów nie udało się wykonać. Trzeba je
odpalić przed scaleniem.

## Czego świadomie NIE zmieniono

Źródła powrotu zadania do kolejki, czyli cichego `assigneeIds: []` w
`ProjectlyClient.create_task()`, gdy nazwa osoby z `escalation_default_assignee`
nie zgadza się z katalogiem Projectly. To osobna decyzja (co ma się stać, gdy
człowieka nie da się rozwiązać: głośny błąd, przypisanie zastępcze, czy zostawienie
bez przypisania) i warto ją podjąć świadomie. Bramka z tej poprawki zatrzymuje
pętlę niezależnie od tego, jak to przypisanie się skończy.
