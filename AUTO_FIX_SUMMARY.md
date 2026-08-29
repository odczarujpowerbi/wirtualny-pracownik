# Naprawa: bramka jakości eskalowała wyniki, których nie miała jak sprawdzić

## Sygnał

Zadanie eskalacyjne "Wymaga decyzji: Naprawa: quality_gate zawodzi powtarzalnie"
wracało w kółko (`block_closed: needs_approval` w każdym cyklu). Zadanie
źródłowe pochodziło z `kacper_monitor.py`, który zakłada zadanie naprawcze po
trzech zdarzeniach `skill_usage:quality_gate:failure`.

## Przyczyna źródłowa (w kodzie tego repo)

`bot_gustaw_bramka.run_gate` liczy `passed` jako "brak odrzuceń ORAZ boty
obowiązkowe zatwierdziły ORAZ zgód >= required_approvals" (dziś próg = 1).
Dla wyniku czysto tekstowego (bez zrzutu ekranu, bez `functional_checks`, bez
`rerun`) wszyscy trzej boci zwracają `skipped`:

* Bartek: brak `rerun` -> `skipped`
* Franek: brak testów funkcjonalnych -> `skipped`
* Oskar: brak zrzutu, narzędzie niewizualne -> `skipped`

Wychodzi 0 zgód przy progu 1, czyli `passed = False`, ale lista zastrzeżeń jest
PUSTA. W `runner_loop._process_task_core` taki wynik wpadał do ostatniej gałęzi
`else` i szedł do człowieka jako zadanie "Wymaga decyzji" z uzasadnieniem
`Zastrzeżenia: brak szczegółów` (pętla poprawek nie ruszała, bo nie ma uwag do
naniesienia). Każde takie zadanie logowało `quality_gate:failure`, więc po
trzech `kacper_monitor` zakładał zadanie naprawcze "quality_gate zawodzi
powtarzalnie", które samo było zwykłym żółtym zadaniem bez workera, więc
przechodziło tę samą ścieżkę i eskalowało się dalej. Stąd powtarzalny sygnał.

Drugie źródło fałszywych alarmów: gałąź `zamkniete_z_feedbackiem` (zadanie źle
postawione) też logowała `quality_gate:failure`, choć bramka wtedy ZADZIAŁAŁA
poprawnie, a gałąź świadomie nie tworzy zadania dla człowieka. Kacper tworzył je
za nią.

## Co zmienione

* `app/bot_gustaw_bramka.py`: `run_gate` zwraca nowe pole `nothing_to_check`
  (wszystkie werdykty `skipped` i zero zastrzeżeń). Pominięcie ZE zastrzeżeniem
  (np. zadanie wizualne bez zrzutu) tego pola nie ustawia, bo wtedy jest co
  powiedzieć człowiekowi. `passed` liczone bez zmian, próg zgód nietknięty.
* `app/runner_loop.py`: nowa funkcja `_decyzja_bramki` rozdziela cztery
  sytuacje (`GATE_PRZESZLO`, `GATE_BEZ_WERYFIKACJI`, `GATE_ZLE_ZADANIE`,
  `GATE_BLOKADA`) zamiast jednego worka "nie przeszło". Przypadek "nie było
  czego sprawdzić" zamyka zadanie jako `done` z jawną adnotacją w komentarzu i
  w polu feedbacku, że automatycznej kontroli jakości NIE było, zamiast zakładać
  człowiekowi zadanie decyzyjne bez treści.
* `app/runner_loop.py`: `quality_gate` loguje `failure` tylko wtedy, gdy bramka
  realnie zablokowała wynik z zastrzeżeniami (gałąź eskalacji). Poprawne
  rozpoznanie źle postawionego zadania i brak czego weryfikować to `success`,
  więc `kacper_monitor` przestaje z tego robić zadania naprawcze.
* `app/README.md`: opis nowego zachowania przy sekcji o bramce.

Zachowanie przy realnej wadzie jakości (odrzucenie bota, przekroczony budżet,
wyjątek w bocie, zastrzeżenie przy pominięciu) jest bez zmian: dalej eskalacja
do człowieka.

## Jak zweryfikować

```
cd app
python validation_gate_smoke_test.py     # 3 nowe asercje wokół nothing_to_check
python runner_loop_smoke_test.py         # nowy plik: 4 ścieżki decyzji po bramce
python poprawka_materialu_smoke_test.py  # regresja pętli poprawek
python kacper_monitor_smoke_test.py      # regresja progów monitora
python self_check.py                     # całość
```

Sprawdzenie na żywym przebiegu: zadanie z wynikiem tekstowym (np. `fetch_url`
bez zrzutu) ma teraz w Projectly komentarz "done (bez automatycznej kontroli
jakości)" i NIE tworzy zadania "Wymaga decyzji".

Uwaga: w środowisku, w którym powstała ta poprawka, uruchamianie Pythona było
zablokowane, więc powyższe testy NIE zostały wykonane. Zmiana była weryfikowana
przez analizę kodu; przed scaleniem uruchom `python self_check.py`.
