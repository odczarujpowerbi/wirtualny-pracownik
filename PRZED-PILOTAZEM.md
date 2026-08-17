# Checklist przed startem pilotażu

Zbiera w jednym miejscu decyzje otwarte, rozproszone dziś po `PLAN-WDROZENIA.md`, `SKRYPTY.md`, `ZESPOL-BOTOW.md` i pierwotnej dokumentacji koncepcyjnej, plus kilka tematów, które nigdzie jeszcze nie padły. Nic z tego nie jest kodem — to decyzje i ustalenia, które trzeba zamknąć przed, nie po, uruchomieniu pierwszej linijki.

## 1. Rejestr decyzji z dokumentacji bazowej — wciąż otwarty

Załącznik D oryginalnego dokumentu koncepcyjnego (`Wirtualny_Pracownik_AI_Dokumentacja_Biznesowa_i_Techniczna.pdf`) zawiera te pytania od sierpnia — żadne nie zostało jeszcze formalnie zamknięte w tej rozmowie:

| ID | Decyzja | Odpowiedzialny | Status |
|---|---|---|---|
| D-01 | Który konkretny komputer i czy obsługuje 32 GB RAM | Właściciel projektu | **Rozstrzygnięte: tak, komputer obsługuje 32 GB.** |
| D-02 | Które 3 procesy mają najwyższą wartość i najniższy poziom ryzyka | Biznes + techniczny | Częściowo: wskazane domeny (Dev, marketing, treści, programy/skrypty/strony/aplikacje) — **wciąż brakuje wyboru 1-3 konkretnych, wąskich procesów** (jak PBI-01/02) w ramach tych domen na start pilotażu. |
| D-03 | Czy istniejący plan Claude zapewnia potrzebną funkcję interaktywną | Właściciel projektu | **Rozstrzygnięte** — patrz notatka niżej. |
| D-04 | Który workspace Power BI i które repo są sandboxem | Power BI owner | Otwarte |
| D-05 | Jaka retencja screenshotów i logów jest akceptowalna | Właściciel danych | Otwarte |
| D-06 | Które działania są zielone, żółte i czerwone (pierwsza wersja `approval_policy.yaml`) | Właściciele procesów | Otwarte |
| D-07 | Kto odbiera alerty i zatwierdza działania poza godzinami | Zespół | Otwarte |

**D-03, notatka:** runner (bot działający 24/7) korzysta z **Anthropic API** (płatność za tokeny) — nie z subskrypcji interaktywnej (Claude Pro/Max, ~500 zł), która jest zaprojektowana pod człowieka przy klawiaturze, nie pod bezobsługową ciągłą pracę. Sterowanie pulpitem, gdy brak API/CLI, realizuje computer use tego samego dostawcy (Anthropic) — nie ma potrzeby wprowadzania drugiego dostawcy AI do sterowania komputerem, bo rozbiłoby to audyt i tryb rozmowy (`PLAN-WDROZENIA.md` sekcja 14) na dwa niespójne źródła. Makra/skrypty deterministyczne to główna dźwignia ograniczania kosztu (sekcja 12: "Python bez AI"). Subskrypcja interaktywna ma zastosowanie gdzie indziej — na komputerze-"warsztacie" (`ZESPOL-BOTOW.md` sekcja 4), do rozwijania i testowania skilli przez Pawła, zanim trafią do komputerów-pracowników.

## 2. Integracje ze statusem "do doprecyzowania"

- **System transakcyjny (sprzedaż)** — `PLAN-WDROZENIA.md` sekcja 6 zaznacza mechanizm API jako "do doprecyzowania po stronie systemu". Bez tego `sales_report_builder.py` (sekcja 18/kategoria P) nie ma się o co oprzeć.
- **Social media (widoczność w sieci)** — które konkretnie platformy (i czy mają API, czy trzeba scrapować/UI) też jeszcze nie ustalone.

## 3. Tematy, które jeszcze nie padły w żadnym dokumencie

- **RODO / zgodność prawna.** Dane realnych klientów (INDEKA, DIVERSE, AXL, Magnapharm) będą przechodzić przez API modeli AI (Anthropic, OpenRouter). Warto zweryfikować warunki przetwarzania danych z dostawcami **przed** tym, jak realne dane klientów zaczną tam trafiać — nie po fakcie.
- **Zespół i zarządzanie zmianą.** Asia, Kacper, Karol i Michał będą mieli swoją pracę analizowaną (`task_retro_auditor.py` czyta ich historię zadań), a część ich zadań przejmie bot (`human_task_partial_executor.py`, intake). Warto ich o tym poinformować zawczasu — bot czytający czyjąś pracę bez wyjaśnienia po co budzi niepokój szybciej niż cokolwiek technicznego w tym planie.
- ~~**Środowisko testowe vs produkcyjne.**~~ **Rozstrzygnięte:** bot dev pracuje domyślnie na próbce/danych szczątkowych z pełnym kontekstem struktury, a zadanie zawiera `source_file_link` — odnośnik do prawdziwego pliku, po który bot sięga, gdy trzeba zweryfikować rozwiązanie na realnym przykładzie. Ani pełna kopia sandboxowa, ani czysta syntetyczna atrapa. Szczegóły: `PLAN-WDROZENIA.md` sekcja 1.
- **Kopie zapasowe samego komputera pilotażowego.** Awaria dysku na jedynej maszynie oznacza utratę nie tylko konfiguracji, ale całego audytu i historii decyzji (`events.jsonl`, `state_store.py` — podstawa trybu rozmowy z sekcji 14). Potrzebny backup poza tą jedną maszyną, nie tylko lokalny snapshot.
- **Projectly jako pojedynczy punkt awarii.** Cały system (kolejka, komunikacja, audyt) stoi na jednej aplikacji. Co się dzieje przy przestoju Projectly — runner czeka bezczynnie, czy ma lokalną kolejkę zapasową?
- **Prowizjonowanie dostępów.** Osiem integracji (Projectly, CRM, Meta Ads, Google Workspace, SharePoint, inFakt, Search Console/Analytics, social media) to sama w sobie realna praca administracyjna — kto i kiedy zakłada konta/klucze/tokeny, zanim faza wdrożenia, która ich potrzebuje, w ogóle się zacznie.
- **Koszt miesięczny — realna liczba, nie tylko zasada.** `PLAN-WDROZENIA.md` sekcja 3 rekomenduje policzenie kosztu (zadania/dzień × wywołania × koszt tokenów) przed wdrożeniem silnika walidacji na produkcję — to wciąż rekomendacja, nie policzona liczba.

## 4. Przypomnienie zakresu — najważniejsze

Po tej serii rozmów plan urósł do: silnika walidacji, obiegu eskalacji, asystenta zadań ludzkich, bibliotek skilli raportowych, intake z maila, harmonogramu i równoległości, zasady "ma zdanie", trybu rozmowy, podsumowań głos/wideo, cyklicznego retro-audytu, kill switcha, cotygodniowych raportów biznesowych z bounded red, oraz całego zespołu botów-ról z agentem strategicznym.

**Pilotaż to nadal tylko Fazy 0-2 (opcjonalnie +3) z `PLAN-WDROZENIA.md`:** fundament komunikacji z Projectly, pętla end-to-end bez ryzyka, silnik walidacji i auto-zatwierdzania, ewentualnie pierwszy proces Power BI/INDEKA. Wszystko powyżej (Fazy 4+, cały `ZESPOL-BOTOW.md`) czeka na dowód, że ten najmniejszy możliwy kawałek działa stabilnie na produkcji przez kilka tygodni. Łatwo to zgubić z oczu przy tylu już zaprojektowanych warstwach — ten dokument ma o tym przypominać.

**Wyjątek — dwie rzeczy z `SKALOWANIE.md` warto zrobić już w Fazie 0**, nie po: rozdzielić kod (rdzeń) od konfiguracji firmy (zamiast zaszywać mapowania klient→osoba na sztywno w skryptach) i założyć od razu model "jedna izolowana instancja na firmę". Zmiana tego po napisaniu 67 skryptów byłaby dużo droższa niż zaprojektowanie tego od pierwszej linijki. Reszta punktów ze `SKALOWANIE.md` (bootstrap floty, klucze per wdrożenie, pakowanie skilli) czeka, aż realnie pojawi się drugi komputer albo druga firma.
