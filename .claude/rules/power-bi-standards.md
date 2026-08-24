# Standard Raportowania Power BI — Odczaruj Low Code

> Standard organizacyjny (Miro: uXjVHRgO3Qs). Obowiazuje wszystkich: agentow, skille, Claude Code.

---

## 1. Format i architektura projektow

- Format: **PBIP z PBIR** — bez wyjatkow. Nigdy PBIX w repozytorium.
- Report pages i visuals: pliki JSON w `.Report/pages/`
- Model semantyczny: pliki TMDL w `.SemanticModel/definition/`
- NIGDY nie twórz PBIP od zera — user musi najpierw stworzyc pusty PBIP w Desktop
- Do zapisu PBIR uzywaj skryptow **Node.js (.mjs)** (unika problemow ze sciezkami ze spacjami)
- Waliduj JSON przed zapisem, auto-wykrywaj wersje schematu z istniejacych wizualizacji

---

## 2. Nazewnictwo tabel

| Prefiks | Typ tabeli |
|---|---|
| `f_` | Tabele faktow |
| `d_` | Tabele wymiarow |
| `p_` | Parametry |
| `dt_` | Tabele odlaczone (disconnected) |
| `brdg_` | Relacje many-to-many (bridge) |
| `Measure` | Tabela miar (tworzona w Power Query) |
| `dCalendar` | Kalendarz (polskie nazwy kolumn dla polskich klientow) |

---

## 3. Nazewnictwo miar i display folderow

- Warianty czasowe: `PY`, `YoY`, `YTD`, `MTD`
- Foldery techniczne: `Formatting` / `Helpers` / `Dynamic`
- Numeracja folderow: `01. Sales`, `02. Margin` (wiodaca liczba wymusza kolejnosc)
- Nazewnictwo miar: `[Prefix Miara]` np. `[SP Sprzedaz Netto]`, `[SP% Marza]`
- Skomplikowane miary obowiazkowo z komentarzem wyjasniajacym logike biznesowa

---

## 4. Dataflow — standard ETL

- Jeden dataflow per zrodlo danych, jeden per czestotliwosc odswiezania
- Schemat nazwy: `<zrodlo>_<czestotliwosc>_<nazwa>` np. `SQL_1D_Fakty`, `Excel_1W_Budzet`
- Metadane obowiazkowe: `nazwa_tabeli`, `nazwa_kolumny`, `opis`

---

## 5. Konfiguracja modelu semantycznego

Obowiazkowe w kazdym modelu:
- Ukrywanie kluczy (relacji)
- Wylaczenie **implicit measures**
- Wylaczenie **auto-date** (uzywamy wlasnego `dCalendar`)

---

## 6. Podzial odpowiedzialnosci

**Backend:** dataflow, walidacja danych wzgledem systemu zrodlowego, tabela meta
**Frontend:** model semantyczny, miary DAX, raport, walidacja regul biznesowych

---

## 7. GIT i wersjonowanie

Struktura SharePoint:
```
\Projekty Raportowania - Dokument\
  nazwa_projektu\
    Raporty\
      NazwaRaportu.pbip\
```
- Commit GIT lokalnie, bez push na GitHub (chyba ze explicite uzgodnione)
- Plik referencyjny (PBIR) na GitHub jako wzorzec

---

## 8. Zarzadzanie wiedza o projekcie

- OneNote per projekt: notatki imienne autora + transkrypcja AI

---

## 9. DAX — dobre praktyki

- Miary zamiast kolumn kalkulowanych wszedzie gdzie mozliwe
- Zawsze `CALCULATE` z odpowiednim kontekstem filtra
- Formatowanie: `FORMAT([Miara], "#,##0.0")`
- `VAR`/`RETURN` dla czytelnosci i wydajnosci w zlozonych miarach
- Unikaj `SUMX` na duzych tabelach bez filtra (ryzyko wydajnosciowe)
- Warianty: `[Miara AC] - [Miara PY]` lub `[Miara AC] - [Miara PL]`

---

## 10. Praca z MCP Power BI

- Desktop **zamkniety** przy bezposrednim zapisie TMDL
- Desktop **otwarty** przy pracy przez MCP (live connection)
- Przy tworzeniu miar DAX: najpierw zaproponuj, czekaj na potwierdzenie, potem zapisz

---

## 11. Wizualizacje — konwencje

Nazewnictwo:
- Strona: `##-NazwaStrony` np. `01-Przeglad`, `02-Sprzedaz`
- Wizualizacja: `##NazwaStrony_##NazwaVisuala` np. `01Przeglad_01KPISprzedaz`

Rozmiary canvas (STANDARD BEZWZGLEDNY):
- Standardowy (HD): `1920 x 1080` (naglowek 0-80px, obszar roboczy 80-1040px, 4 kolumny ~460px)
- Rozszerzony (scrollable): `1920 x 1800` (naglowek 0-80px, obszar roboczy 80-1760px)
- NIGDY `1280x720` (stary standard)

Biblioteka wizualek: SVG, HTML, Deneb. Theme wspolny jako punkt wyjscia, zawsze dostosowywany.

Typy wizualizacji (identyfikatory PBIR):
- KPI card: `cardVisual` lub `card`
- Tabela: `tableEx`
- Macierz: `pivotTable`
- Slupkowy poziomy: `clusteredBarChart`
- Slupkowy pionowy: `clusteredColumnChart`
- Liniowy: `lineChart`
- Combo: `lineClusteredColumnComboChart`
- Slicer: `slicer`

---

## 12. IBCS — standardy wykresow wariancji

Szablony gdy porownujesz AC vs PY lub PL:
- Column Variance: `ibcs-column-variance` (15 miar DAX)
- Bar Variance: `ibcs-bar-variance` (2-4 DAX + NativeVisualCalculation)
- Variance Table Simple: `ibcs-table-simple` (2-3 miary SVG)

| Kolor | Hex | Zastosowanie |
|---|---|---|
| `#333333` | Czarny | AC (Actual) |
| `#AAAAAA` | Szary | PY (Prior Year) |
| `#000000` | Czarny | PL (Plan) |
| `#18A558` | Zielony | Pozytywna wariancja |
| `#E84040` | Czerwony | Negatywna wariancja |

---

## 13. Analiza zaleznosci (Dependency Analyzer)

Klasyfikacja obiektow przy audycie modelu:
- **V** — uzyte w wizualizacji
- **O** — osierocone (orphaned), kandydaci do usuniecia
- **BROKEN** — uszkodzone referencje, naprawa natychmiastowa
- **CIRC** — zaleznosci kolowe, krytyczny blad modelu

Ostrzezenia jakosci: M2M relationships, dwukierunkowe filtry, wyspy (islands).

---

## 14. Wymagania projektowe (Requirements Gathering)

10 faz przed budowa raportu:
1. Kontekst biznesowy i sponsoring
2. Dane i zrodla
3. Model semantyczny
4. Wydajnosc i skalowalnosc
5. Administracja i Storage Mode
6. Wymagania wizualne
7. Bezpieczenstwo i RLS
8. Integracje i logika biznesowa
9. Governance i standardy workspace
10. Zarzadzanie zmiana i szkolenia

Produkt: dokument wymagań (MD) + podsumowanie HTML z risk register.
