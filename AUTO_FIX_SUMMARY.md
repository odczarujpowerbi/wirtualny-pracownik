# Auto-fix: agent eskalował własne eskalacje w kółko

## Co się zepsuło

Zadanie z sygnałem `eskalacja_do_czlowieka` miało tytuł:

```
Wymaga decyzji: Feedback: Wymaga decyzji: Wymaga decyzji: Zbierz dane o Looker Studio, Metabase i Superset (fetch_url)
```

Ten narastający tytuł to cała diagnoza. Agent przetwarzał zadania, które sam
założył DLA CZŁOWIEKA:

1. `escalation.escalate_to_human` tworzy zadanie „Wymaga decyzji: <tytuł>”
   przypisane do osoby z `escalation_default_assignee`.
2. Gdy tej osoby nie ma w katalogu Projectly, `create_task` szedł z pustym
   `assigneeIds`, a Projectly przypisuje takie zadanie wg uprawnień tokenu,
   czyli z powrotem kontu AI, które je utworzyło.
3. `runner_loop` brał je w `get_new_tasks` jak zwykłe zadanie. Nie ma tu czego
   wykonać (to pytanie do człowieka), więc bramka jakości odrzucała wynik i
   agent eskalował je PONOWNIE, doklejając kolejny przedrostek.
4. `task_feedback_requester` dokładał do tego „Feedback: …” — również
   przypisane do konta AI, bo brał `assignee` zamkniętego zadania (czyli bota).

Efekt dla człowieka: kolejne kopie tego samego pytania w Projectly i ciąg
`block_closed: needs_approval` w dzienniku bez żadnego postępu.

## Co zmieniono

- **`app/meta_task_guard.py` (nowy)** — rozpoznaje zadania META założone przez
  agenta (`Wymaga decyzji:`, `Feedback:`, `Kontynuacja:`) i buduje ich tytuły
  IDEMPOTENTNIE (`escalation_title`, `continuation_title`, `feedback_title`
  zdejmują istniejące przedrostki zamiast doklejać kolejny).
- **`app/runner_loop.py`** — próg na wejściu `_process_task_core`: zadanie
  należące do człowieka (eskalacja / prośba o feedback) jest odkładane ze
  statusem `waiting_human`, bez komentarza, bez zmiany statusu w Projectly i
  bez kolejnej eskalacji. Ślad `escalation_task_skipped` w dzienniku zapisywany
  RAZ na zadanie, nie co cykl pollowania.
- **`app/escalation.py`** — tytuły eskalacji i kontynuacji przez
  `meta_task_guard` (eskalacja eskalacji daje ten sam tytuł).
- **`app/task_feedback_requester.py`** — nie pyta o feedback do zadań META, a
  prośbę o feedback z pracy konta AI kieruje do człowieka
  (`FEEDBACK_HUMAN_ALIAS`), nie z powrotem do bota.
- **`app/projectly_client.py`** — `_resolve_person_id` zgłasza w logu nazwę
  osoby, której nie ma w katalogu Projectly (dotąd zadanie po cichu powstawało
  bez przypisania, czyli wracało do konta AI). `_is_ai_account` wydzielone do
  funkcji modułowej `is_ai_account_name`, żeby mogły z niej korzystać moduły
  bez klienta pod ręką.
- **`app/meta_task_guard_smoke_test.py` (nowy)** — test dymny: zdejmowanie
  zagnieżdżonych przedrostków z realnego tytułu z incydentu, idempotencja
  tytułów, pominięcie zadania dla człowieka w runnerze (zero wywołań klienta,
  brak `block_closed`, jeden wpis w dzienniku mimo dwóch cykli), eskalacja
  eskalacji z jednym przedrostkiem, filtr i adresat prośby o feedback.
- **`app/README.md`** — wiersz o nowym module.

Nic nie usunięto; zmiany są dokładane, a `Kontynuacja:` celowo NIE jest
traktowana jak zadanie dla człowieka (to zadanie dla agenta, z decyzją
człowieka już wbudowaną w opis).

## Jak zweryfikować

```bash
cd app
python meta_task_guard_smoke_test.py   # nowy test dymny
python self_check.py                   # cały zestaw testów dymnych (regresja)
```

Uwaga uczciwościowa: w środowisku, w którym powstała ta poprawka, uruchamianie
Pythona było zablokowane uprawnieniami, więc powyższych testów NIE udało się
odpalić. Kod i test są napisane pod konwencję repo (`*_smoke_test.py` wpina się
automatycznie w `self_check.py`) i wymagają jednego przebiegu przed scaleniem.

Weryfikacja na żywo (po wdrożeniu): w Projectly nie powinny już powstawać
zadania z podwójnym przedrostkiem w tytule, a w dzienniku zadania
eskalacyjnego ma być jeden wpis `escalation_task_skipped` zamiast ciągu
`block_closed: needs_approval`. Jeśli w logu runnera pojawi się ostrzeżenie
„Osoby '…' nie ma w katalogu Projectly”, popraw `escalation_default_assignee` /
`people_aliases` w `app/config/projectly.yaml` — to jest pierwotna przyczyna
tego, że eskalacje w ogóle wracały do bota.
