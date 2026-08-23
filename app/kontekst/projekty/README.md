# Kontekst projektów

Jeden plik na projekt. To, czego nie widać w samym zadaniu: kto jest po drugiej
stronie, z jakich systemów korzysta, na jakim etapie jesteśmy, co już ustalone
i czego przy tym kliencie nie wolno zrobić.

Nazwa pliku = nazwa projektu z Projectly, małymi literami, spacje jako myślniki:
`DEV - Magnapharm` → `dev-magnapharm.md`. Dzięki temu `kontekst_firmy.py` dobiera
plik automatycznie, gdy nazwa projektu pada w zadaniu.

## Skąd się biorą

`python kontekst_projektow_seed.py --yes` tworzy szkice z danych w Projectly
(nazwa, marka, liczba zadań, tematy, z jakich zadań się składa). Szkic zawiera
sekcje `[do uzupełnienia]` — to miejsca, których żadne dane w Projectly nie
wypełnią, bo są w głowie właściciela. Generator **nigdy nie nadpisuje** pliku,
który ktoś już uzupełnił.

## Zasady

1. Krótko — projekt opisujemy w kilkunastu linijkach, nie w dokumentacji.
2. Ustalenia z klientem zapisujemy tu, a nie w komentarzach zadań, bo tam giną.
3. Poufność: te pliki zostają wewnątrz repo. W materiałach dla klientów i w
   publikacjach nazwy klientów nie padają (patrz `firma-podstawy.md`).
4. Projekt zakończony przenosimy do `zakonczone/` zamiast kasować — wraca kontekst,
   gdy klient odezwie się po roku.
