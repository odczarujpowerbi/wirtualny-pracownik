# Git Workflow — zasady commitów

## Konwencja commitów (STANDARD ORGANIZACYJNY)

Każda zmiana w plikach projektu = osobny commit z numerem sekwencyjnym i krótkim opisem po polsku.

**Format:** `[numer dwucyfrowy] - [opis zmiany po polsku]`

### Przykłady
```
00 - pusty
01 - inicjalizacja projektu
02 - dodano stronę główną
04 - dodano CLAUDE.md i ulepszono opisy commitów
16 - dodano wybór waluty w kalkulatorze napiwku
```

### Zasady

- Numer zawsze dwucyfrowy: `01`, `02`, ..., `10`, `11`, ...
- Opis po polsku, zwięzły — co zostało zrobione (nie dlaczego)
- Jeden logiczny krok = jeden commit (nie łącz niezwiązanych zmian)
- Sprawdź ostatni numer przez `git log --oneline` i zwiększ o 1
- Pierwszy commit w nowym repo: `00 - pusty` (pusty plik .gitkeep lub inicjalizacja) albo `01 - [pierwsza zmiana]`
- Commituj samodzielnie po zakończeniu logicznego kroku pracy (nie czekaj na wyraźną prośbę usera). Nie pushuj na zdalne repo bez zgody.

### Workflow przy każdym commicie

1. `git log --oneline -1` — sprawdź ostatni numer
2. Staguj konkretne pliki (nie `git add -A` bez sprawdzenia)
3. Commit z formatem: `[następny numer] - [opis]`
