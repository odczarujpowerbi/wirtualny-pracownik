# Plan wdrożenia i komunikacji — Wirtualny Pracownik AI (v2, Projectly-centric)

Ten plan rozwija dokumentację koncepcyjną (`Wirtualny_Pracownik_AI_Dokumentacja_Biznesowa_i_Techniczna.pdf`) o konkretne narzędzia, którymi realnie dysponujemy: **Projectly** (własna apka do zadań, API + MCP) jako główny kanał komunikacji, CRM przez MCP, Meta Ads (API + UI), Google Workspace, SharePoint, agent e-mailowy przez MCP, oraz bibliotekę skilli z botem, który sam je ulepsza.

Główny problem, który ten plan rozwiązuje: **administrator traci czas na ręczne zatwierdzanie każdego zadania.** Rozwiązaniem jest silnik walidacji z kilkoma niezależnymi walidatorami działającymi równolegle — administrator zatwierdza już tylko wyjątki (czerwone/sporne), nie każdą pojedynczą akcję.

Ten dokument opisuje architekturę **jednego** pracownika. Docelowa wersja wieloosobowa (kilka botów-ról na osobnych komputerach, agent strategiczny doradzający prezesowi) jest osobnym rozwinięciem w [ZESPOL-BOTOW.md](./ZESPOL-BOTOW.md) — budowanym dopiero po ustabilizowaniu tego, co tutaj opisane.

## 1. Zasada nadrzędna: rezultat, nie instrukcja

Zadanie w Projectly opisuje **oczekiwany rezultat i kryteria akceptacji**, nie krok po kroku co robić. Planner AI sam dekomponuje zadanie na kroki, wybiera narzędzia i skrypty, wykonuje, a na końcu **sam ocenia własny wynik** względem kryteriów, zanim cokolwiek trafi do człowieka.

Minimalny kontrakt zadania (pole w Projectly lub JSON w treści/komentarzu):

```json
{
  "task_id": "PRJ-1042",
  "title": "Przygotuj raport sprzedaży Q3 w Power BI",
  "expected_result": "PBIP z zaktualizowanym modelem, 3 strony raportu, brak błędów walidacji",
  "acceptance_criteria": [
    "Model przechodzi walidację TMDL bez błędów krytycznych",
    "Każda strona ma zrzut ekranu bez elementów wychodzących poza obszar",
    "Dane zgadzają się z sumą kontrolną ze źródła"
  ],
  "source_file_link": "https://.../sales_q3_source.xlsx",
  "risk_level_hint": "yellow",
  "max_ai_cost_usd": 3.0,
  "created_by": "pawel"
}
```

### Praca na próbce z pełnym kontekstem, nie na pełnej kopii ani czystej atrapie

Odpowiedź na pytanie ze `PRZED-PILOTAZEM.md` ("środowisko testowe vs produkcyjne, sandbox czy żywe repo") jest środkiem między tymi dwiema skrajnościami:

- Bot dev domyślnie **nie pobiera i nie przetwarza całego pliku źródłowego** — pracuje na próbce/danych szczątkowych (np. pierwsze N wierszy, zamaskowane wartości wrażliwe) wystarczającej do zrozumienia struktury i zbudowania logiki. To taniej (mniej tokenów, szczególnie przy dużych plikach) i bezpieczniej (mniej pełnych danych klienta w kontekście modelu).
- Ale ma **pełen kontekst** — metadane o strukturze całego pliku (schemat, liczba wierszy, historia zmian z `source_schema_watcher.py`, kontrakt z `data_contract_validator.py`) — więc próbka nie jest zgadywaniem w ciemno.
- Zadanie od człowieka zawsze zawiera **`source_file_link`** — bezpośredni odnośnik do prawdziwego pliku, nie jego treść wklejoną do zadania. Gdy rozwiązanie faktycznie wymaga zweryfikowania na realnym przykładzie (np. czy naprawiona logika PQ działa na prawdziwych danych, nie tylko na próbce), bot sięga po link i wykonuje operację na nim przez skrypt — nadal w granicach zwykłej klasyfikacji ryzyka (odczyt pliku = zielone, zmiana = żółte/czerwone zależnie co to za plik).
- To eliminuje fałszywy wybór między "kopiuj wszystko do sandboxa" (kosztowne, trzeba utrzymywać drugą wersję każdego źródła) a "pracuj wyłącznie na syntetycznych atrapach" (nie łapie realnych przypadków brzegowych, które są dokładnie tym, co psuje raporty w INDECE/DIVERSE — sekcja 10).

## 2. Komunikacja: Projectly jako jedyne źródło prawdy

- **Kanał główny i jedyny obowiązkowy:** komentarze na zadaniu w Projectly. Żadnego równoległego "prawdziwego" stanu w Discordzie czy mailu — Projectly to system rekordu.
- **Szablon komentarza po zakończeniu pracy** (zawsze ten sam format, żeby dało się go czytać w 10 sekund):

  ```
  ✅ / ⚠️ / ❌ [status]
  Co zrobiono: <2-4 zdania>
  Jak zweryfikowano: <lista walidatorów i wynik>
  Koszt: X USD | Czas: Y min
  Pliki/linki: <PR, screenshoty, raport>
  Wymaga decyzji: <tak/nie — jeśli tak, co konkretnie i dlaczego>
  ```

- **Status zadania w Projectly** odzwierciedla stan wewnętrzny runnera: `queued → planning → running → validating → (auto-approved | needs_approval) → done / failed`.
- **Decyzja człowieka** = komentarz lub zmiana statusu w Projectly, parsowany przez pollera jako `approve` / `reject` / `changes_requested`. Nie ma osobnego kanału do klikania "zatwierdź" — wszystko dzieje się tam, gdzie i tak żyje zadanie.
- Powiadomienie push/e-mail o pozycji "wymaga decyzji" jest opcjonalne — do dograć, jeśli Projectly nie powiadamia natywnie o nowych komentarzach/statusach.

### Status na żywo — moduł analizy pracy w toku, nie tylko zakończonych zadań

Komentarz po zakończeniu zadania (wyżej) i `digest_generator.py` (sekcja 10) mówią, **co już się stało**. To nie wystarcza — potrzebny jest też widok tego, **co dzieje się teraz**, zanim zadanie się skończy, i widok zdrowia całej pracy w toku, nie tylko pojedynczego zadania.

- **`live_status_publisher.py`** (harmonogram: co 1-2 min, ta sama częstotliwość co `watchdog.py`) — utrzymuje w Projectly **jeden, stały, nigdy niezamykany wpis per bot-rola** (np. "🟢 Status: Krzysztof-dev"), który jest **nadpisywany**, nie dopisywany jak komentarze na zwykłych zadaniach. Zawiera:
  - aktualne zadanie w toku i postęp (np. "krok 3/5: walidacja PBIP"), albo "bezczynny — czeka na zadanie",
  - czas ostatniego heartbeatu,
  - liczbę zadań w kolejce i liczbę czekających na decyzję człowieka (`needs_approval`),
  - koszt AI dziś / w tym tygodniu,
  - zdrowie: OK / ALERT (z `watchdog.py`).
- To jest **osobny mechanizm od digestu i trybu rozmowy** (sekcje 10 i 14): digest podsumowuje po fakcie, tryb rozmowy odpowiada na żądanie, status na żywo jest **zawsze widoczny bez pytania** — jeden rzut oka na Projectly pokazuje, co robi każdy bot teraz, nie tylko co zrobił.
- Przy jednym pracowniku to jeden wpis. Przy wielu rolach (`ZESPOL-BOTOW.md`) to naturalnie staje się widokiem całej floty naraz — dokładnie to, czego potrzebuje przyszły "Operator floty" (`ZESPOL-BOTOW.md` sekcja 1).

## 3. Silnik walidacji i auto-zatwierdzania (rdzeń rozwiązania problemu)

Klasyfikacja ryzyka zostaje z oryginalnego dokumentu (zielone/żółte/czerwone), ale dochodzi **warstwa wielu niezależnych walidatorów głosujących nad żółtymi akcjami**, żeby człowiek nie musiał klikać za każdym razem.

```
              ┌─────────────────┐
 zadanie ───▶ │ risk_classifier  │
              └────────┬─────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼               ▼              ▼
    ZIELONE          ŻÓŁTE         CZERWONE
   auto, bez      3 walidatory    zawsze zadanie
   walidacji      równolegle      dla człowieka
        │               │         (sekcja 4)
        │        ┌──────┴──────┐
        │        ▼      ▼      ▼
        │     testy   wizualny  zgodność
        │   techniczne (vision)  z zakresem
        │        │      │      │
        │        └──────┼──────┘
        │               ▼
        │       ≥2/3 zgody? ──tak──▶ auto-approve,
        │               │            pełny log w Projectly
        │               nie
        │               ▼
        │          zadanie dla człowieka
        │          (sekcja 4, jak w czerwonych)
        ▼               ▼
     DONE           komentarz + status w Projectly
```

- **Zielone** (odczyt, screenshot, raport, draft) — zero walidacji, zapis do audytu i komentarz "na koniec dnia" zbiorczy, żeby nie zaśmiecać Projectly.
- **Żółte** (commit na gałęzi, aktualizacja CRM, draft maila, zmiana statusu) — walidatory głosują, próg 2 z 3 do auto-zatwierdzenia. Poniżej progu → zadanie dla człowieka (sekcja 4), dokładnie ten sam mechanizm co dla czerwonych.
- **Czerwone** (publikacja, budżet reklamowy, wysyłka masowa, usunięcie danych, nadanie roli) — **domyślnie zawsze** trafiają do człowieka, niezależnie od wyniku walidatorów. Wyjątek: **czerwone w granicach** (bounded autonomy), patrz niżej.
- Reguły klasyfikacji i progi trzymane w `approval_policy.yaml` — edytowalne bez zmiany kodu, żeby można było kręcić progiem "ile walidatorów musi się zgodzić" per typ zadania.
- Gdy walidatory się nie zgadzają albo mają niską pewność — to **nie jest błąd, to sygnał** do eskalacji, nie do zgadywania.
- **Kalibracja liczby walidatorów pod kątem kosztu:** 3 walidatory na każde żółte zadanie to koszt, nie tylko rygor — 3 dodatkowe wywołania modelu (część vision, najdroższe tokeny) do każdej zmiany. Dla typów zadań z ugruntowaną historią sukcesu (`skill_usage_logger.py` pokazuje wysoką skuteczność) liczba walidatorów w `approval_policy.yaml` powinna spaść do 1; pełne 3 zostają dla nowych/nieprzetestowanych typów zadań. Bez tej kalibracji hasło "bardzo tani pracownik" nie będzie prawdziwe w praktyce — warto policzyć realny koszt miesięczny (liczba zadań/dzień × wywołania × koszt tokenów) zanim silnik trafi na produkcję.
- **Zasada domyślna: agent radzi sobie sam.** Zadanie dla człowieka to wyjątek zarezerwowany dla decyzji, które faktycznie wymagają człowieka (autoryzacja czerwona, brakująca wiedza/dostęp, czynność prawna/fizyczna) — nie sposób na zrzucenie pracy, którą agent mógłby wykonać sam.
- **Czerwone w granicach (bounded autonomy)** — decyzja podjęta świadomie: dla wybranych typów czerwonych akcji (na start: zmiany budżetu reklamowego w zdefiniowanych widełkach) agent wykonuje **bez pytania**, jeśli mieści się w jawnie zdefiniowanej granicy liczbowej w `approval_policy.yaml` (np. „budżet dzienny kampanii Meta Ads: autonomicznie w zakresie ±15%, poza tym — zwykłe czerwone do człowieka”). Poza granicą ta sama akcja wraca do zwykłego trybu czerwonego (sekcja 4). To dokładnie faza D „Ograniczona autonomia” z dokumentacji bazowej (rozdz. 17) — nie nowy wymysł, tylko domknięcie mapy rozwoju, która już to przewidywała.
  - **Granice ustawia człowiek, nie bot.** Agent nigdy sam nie rozszerza ani nie zgaduje granicy — brak zdefiniowanej granicy dla danego typu akcji = zwykłe czerwone.
  - **Bounded red nadal przechodzi przez `validator_pool.py`** jak żółte — granica liczbowa to warunek konieczny, nie wystarczający.
  - **Każde wykonanie w granicach trafia widocznie do cotygodniowego digestu** (`digest_generator.py`), nawet jeśli nie wymagało akceptacji — żeby nic nie „ucichło" tylko dlatego, że nie wymagało kliknięcia.
  - **Rekomendacja startowa: pusta lista granic.** Zacząć z `approval_policy.yaml` bez żadnych bounded red, uruchomić zwykły tryb czerwony (sekcja 4) na produkcji przez kilka tygodni, i dopiero po zbudowaniu zaufania do konkretnego typu akcji (widoczne w KPI z sekcji 8) dodawać granicę dla tego jednego typu — nie wszystkich naraz.

## 4. Obieg eskalacji: zadanie dla człowieka → komentarz → weryfikacja → kontynuacja

Kiedy agent trafia na czerwoną akcję albo żółtą bez zgody walidatorów, **nie zostawia samego komentarza z prośbą o decyzję — tworzy w Projectly osobne, dobrze opisane zadanie przypisane do konkretnej osoby** (Paweł albo wskazany pracownik). Człowiek wykonuje je jak każde inne zadanie, agent odbiera efekt i kontynuuje pracę przy najbliższym obiegu.

```
 agent napotyka        ┌──────────────────────────┐
 czerwoną akcję   ───▶ │ tworzy zadanie w Projectly│
 lub sporne żółte      │ przypisane człowiekowi:   │
                        │ - co jest potrzebne       │
                        │ - dlaczego (kontekst)     │
                        │ - screenshoty/diff/opcje  │
                        └────────────┬─────────────┘
                                     ▼
                         człowiek robi zadanie,
                         zostawia komentarz z wynikiem
                                     ▼
                     ┌───────────────────────────────┐
                     │ human_response_validator.py    │
                     │ czy komentarz odpowiada na to,  │
                     │ o co faktycznie proszono?       │
                     └──────┬────────────────┬────────┘
                            │ tak            │ nie
                            ▼                ▼
              agent tworzy sobie      agent dopytuje —
              zadanie-kontynuację     nowy komentarz z
              w Projectly z decyzją   konkretnym pytaniem,
              człowieka wbudowaną      zadanie zostaje otwarte
              w kontekst
                            ▼
              wykonanie przy najbliższym
              obiegu runnera (poller odbiera
              własne zadanie jak każde inne)
```

- **Zadanie, nie tylko komentarz.** Człowiek widzi je tam, gdzie i tak pracuje (Projectly), z priorytetem i kontekstem — nie musi pamiętać, żeby wrócić do wątku w komentarzach.
- **Weryfikacja odpowiedzi to osobny krok.** `human_response_validator.py` sprawdza, czy komentarz faktycznie rozstrzyga sprawę (np. jednoznaczne "zatwierdzam"/"nie" przy czerwonej akcji, konkretna wartość przy brakującej informacji) — jeśli nie, agent dopytuje zamiast zgadywać albo ruszać dalej na niejasnej podstawie. To ta sama zasada fail-closed co przy walidacji żółtych.
- **Kontynuacja to nowe zadanie agenta w Projectly**, nie automatyczny "resume" w tle — dzięki temu cały tok pracy (oryginalne zadanie → eskalacja → decyzja → kontynuacja) jest widoczny jako ciąg powiązanych zadań, a nie ukryty w logach.
- Runner podnosi zadanie-kontynuację na tych samych zasadach co każde inne — poller nie rozróżnia "swoich" i "cudzych" zadań, tylko sprawdza, do kogo są przypisane.

## 5. Bot jako asystent zadań ludzkich (proactive assist)

Poza własną kolejką agent cyklicznie **przegląda też zadania przypisane ludziom** w Projectly i szuka, gdzie może pomóc — nie po to, żeby przejmować ich pracę, tylko żeby ją skrócić.

| Sytuacja | Co robi agent | Efekt |
|---|---|---|
| Zadanie człowieka da się częściowo zautomatyzować | Wykonuje automatyzowalną część, zostawia komentarz "zrobiłem X, zostaje Ci Y" | Człowiekowi zostaje tylko to, czego naprawdę nie da się zautomatyzować |
| Zadanie wymaga researchu/przygotowania, ale decyzję/wykonanie musi podjąć człowiek | Przygotowuje opracowanie (research, draft, porównanie opcji) i dołącza jako komentarz/załącznik | Człowiek zaczyna od gotowego materiału zamiast białej kartki |
| Zadanie jest w pełni ludzkie (rozmowa, decyzja strategiczna, czynność fizyczna) | Nic nie robi automatycznie — najwyżej odnotowuje, że sprawdził i zadanie faktycznie wymaga człowieka | Brak fałszywych "usprawnień" tam, gdzie ich nie potrzeba |

- Agent **nie przejmuje właścicielstwa** zadania człowieka i nie oznacza go jako zakończone — dopisuje tylko efekt swojej pracy jako komentarz, decyzję o zamknięciu zostawia człowiekowi.
- To przeglądanie działa na tych samych zielonych zasadach co reszta odczytu — nie wymaga zatwierdzenia, bo nic nieodwracalnego się nie dzieje.
- Cel: **w większości przypadków agent daje sobie radę sam** (albo w pełni, albo dowożąc 80% pracy do zadania człowieka) — eskalacja z sekcji 4 zostaje dla przypadków, gdzie to faktycznie niemożliwe.

## 6. Integracje — kolejność wdrożenia i sposób podłączenia

| Integracja | Mechanizm | Ryzyko domyślne | Uwaga |
|---|---|---|---|
| Projectly | REST API + MCP | infra (bez ryzyka biznesowego) | Kolejka zadań, komentarze, status — rdzeń komunikacji |
| CRM | MCP | żółte (odczyt: zielone) | Zapis/zmiana rekordów przez walidatory; masowe operacje = czerwone |
| Meta Ads | API (główne) + Playwright (fallback UI) | budżet/publikacja = czerwone, **w zdefiniowanych widełkach: bounded red** | Zmiana budżetu w granicach z `approval_policy.yaml` autonomicznie (sekcja 3), poza granicą — zwykłe czerwone |
| Google Workspace | Google API (Docs/Sheets) | żółte | Tworzenie/aktualizacja plików roboczych |
| SharePoint | Microsoft Graph | żółte | Upload/aktualizacja artefaktów, audytu, raportów |
| Power BI | PBIP/TMDL + Desktop Bridge | odczyt: zielone, zmiana: żółte, publikacja: czerwone | Zgodnie z PBI-01/PBI-02 z dokumentacji bazowej |
| E-mail (wychodzący) | MCP → dedykowany agent mailowy | wysyłka = **zawsze czerwone** | Bot deleguje redakcję/wysyłkę do wyspecjalizowanego agenta przez MCP, nie wysyła bezpośrednio |
| E-mail (przychodzący) — intake | MCP/Graph, odczyt skrzynki | zielone (samo utworzenie zadania) | Bot czyta i klasyfikuje, tworzy zadanie w Projectly — patrz sekcja 11 |
| System transakcyjny (sprzedaż) | API/MCP (do doprecyzowania po stronie systemu) | zielone (odczyt) | Źródło dla raportu sprzedażowego — sekcja 18 |
| inFakt (księgowość) | API jeśli dostępne, inaczej eksport CSV z portalu — **dedykowane konto bota** | odczyt: zielone, jakakolwiek zmiana danych księgowych: **zawsze czerwone, bez granic** | Księgowość celowo bez bounded red na starcie — zbyt wrażliwe, żeby uczyć się na granicach |
| Google Search Console + Analytics | API | zielone | SEO, ruch na stronie — źródło raportu widoczności, sekcja 18 |
| Social media (zasięgi, wzmianki) | API per platforma (do doprecyzowania które) | zielone | Drugie źródło raportu widoczności, sekcja 18 |
| Dev tools (git, testy, deploy) | CLI/skrypty | commit na gałęzi: żółte, merge/deploy: czerwone | Standardowy flow branch → PR → decyzja |

## 7. Fazy wdrożenia

| Faza | Zakres | Rezultat | Czas |
|---|---|---|---|
| 0. Fundament komunikacji | Dostęp do Projectly API/MCP, kontrakt zadania, szkielet runnera + heartbeat | Runner potrafi odczytać i zaktualizować testowe zadanie | 2-3 dni |
| 1. Pętla end-to-end (bez ryzyka) | Poller → wykonanie prostego skryptu → komentarz w Projectly | Pełny cykl queued→done widoczny w Projectly, zero klikania | 3-5 dni |
| 2. Silnik walidacji i auto-zatwierdzania | risk_classifier, validator_pool (min. 3 walidatory), auto-approve żółtych | Administrator przestaje ręcznie zatwierdzać żółte zadania | 4-6 dni — **priorytet nr 1** |
| 2b. Obieg eskalacji i zadania dla ludzi | escalate_to_human.py, human_response_validator.py, continuation_task_creator.py (sekcja 4) | Czerwone/sporne trafiają jako opisane zadania, nie tylko komentarze; agent sam kontynuuje po decyzji | 3-5 dni — równolegle z Fazą 2 |
| 3. Screenshoty + Power BI | Wspólne narzędzie do zrzutów, PBI-01 (walidacja), PBI-02 (bezpieczna korekta) | Pierwszy pełny proces biznesowy działa end-to-end | 5-8 dni |
| 4. CRM + Meta Ads | Integracja API, walidatory specyficzne dla domeny | Odczyt i kontrolowane zmiany w CRM/kampaniach | 5-8 dni |
| 5. Google Workspace + SharePoint | Tworzenie plików, synchronizacja artefaktów | Bot samodzielnie produkuje i archiwizuje dokumenty | 3-5 dni |
| 6. E-mail przez agenta MCP | Most do dedykowanego agenta mailowego, walidator treści przed wysyłką | Bot przygotowuje maile, wysyłka zawsze z akceptacją | 2-4 dni |
| 7. Asystent zadań ludzkich | human_task_scanner.py, częściowa automatyzacja, przygotowywanie opracowań (sekcja 5) | Agent skraca zadania ludzi, nie tylko realizuje własne | 3-5 dni, po Fazie 2b |
| 8. Biblioteka skilli + bot ulepszający | Rejestr skilli, logowanie skuteczności, cykliczna analiza i propozycje poprawek | Skille poprawiają się same na podstawie danych z produkcji | Ciągłe, start równolegle z Fazą 2 |
| 9. Skille raportowe, porządkowanie danych i podsumowania | report_builder.py, data_tidy.py, source_schema_watcher.py, newsletter_drafter.py, digest_generator.py (sekcja 10) | Największy zmierzony koszt (INDEKA/DIVERSE firefighting, ~175h w próbce) zaczyna spadać | 5-8 dni — **priorytet nr 2** po silniku walidacji |
| 10. Intake — rozdzielanie zadań z maila i innych źródeł | email_intake_triage.py, task_routing_classifier.py, routing_confidence_check.py (sekcja 11) | Zadania powstają i trafiają do właściwej osoby/bota bez ręcznego zakładania w Projectly | 4-6 dni, po Fazie 9 |
| 11. Raporty biznesowe cykliczne | sales_report_builder.py, ad_spend_report_builder.py, infakt_export.py, company_financial_report_builder.py, web_visibility_report_builder.py, weekly_business_review.py (sekcja 18) | Cotygodniowa analiza sprzedaży/wydatków/finansów/widoczności z gotowym planem wdrożenia | 8-12 dni, po Fazach 2b i 9 — **wymaga dojrzałego silnika walidacji, bo dotyka pieniędzy** |
| 12. Stabilizacja i metryki | KPI z dokumentacji bazowej (powtarzalność, koszt/zadanie, liczba eskalacji) | Decyzja: rozwijamy / iterujemy / zatrzymujemy | 4-8 dni |

## 8. Metryka sukcesu specyficzna dla tego problemu

Oprócz kryteriów z dokumentacji bazowej (rozdz. 13), dodatkowy KPI dla tego wdrożenia:

| KPI | Definicja | Cel |
|---|---|---|
| Ręczne zatwierdzenia / 100 zadań | Liczba żółtych zadań, które i tak trafiły do człowieka mimo silnika walidacji | Trend malejący, docelowo tylko czerwone + sporne |
| Zgodność walidatorów | Odsetek żółtych zadań, gdzie walidatory osiągnęły próg zgody bez eskalacji | Rosnący w miarę kalibracji progów |
| Czas do decyzji człowieka | Od utworzenia zadania dla człowieka do jego odpowiedzi w Projectly | Mierzony, nie musi maleć — ale nie powinien blokować kolejki |
| Dopytania po odpowiedzi człowieka | Odsetek przypadków, gdzie `human_response_validator.py` uznał komentarz za niewystarczający | Niski i stabilny — wysoki wskazywałby na źle sformułowane zadania dla ludzi |
| Wsparcie zadań ludzkich | Liczba zadań ludzi, gdzie agent wykonał część lub przygotował opracowanie | Rosnący — miara realnej odciążki, nie tylko własnej kolejki agenta |
| Godziny firefightingu danych (INDEKA/DIVERSE-owy wzorzec) | Godziny na "przepięcie"/"błąd w PQ"/"komunikacja o zmianach w pliku" wg raportu godzin | Malejący z miesiąca na miesiąc od wdrożenia Fazy 9 |
| Trafność auto-routingu zadań | Odsetek zadań z intake, których przypisanie nie wymagało ręcznej korekty | Rosnący w miarę kalibracji `task_routing_classifier.py` |

## 9. Bezpieczeństwo — bez zmian względem zasady nadrzędnej

Auto-zatwierdzanie żółtych **nie zmienia** zasady fail-closed z dokumentacji bazowej: jeśli agent nie jest pewny konta/aplikacji/rezultatu, to i tak zatrzymuje się i eskaluje — walidatory nie "przegłosowują" niepewności agenta, tylko potwierdzają jakość już wykonanej, jednoznacznej pracy. Czerwone pozostają zawsze poza automatycznym zatwierdzeniem, niezależnie od tego, ile walidatorów by się zgodziło.

## 10. Skille raportowe, porządkowanie danych i podsumowania

Wynik z analizy realnego raportu godzin (kwiecień-sierpień 2026): **ok. 175h w pierwszej próbce to firefighting wokół danych** dla INDEKA i DIVERSE — powtarzający się wzorzec "właściciel pliku źródłowego (Michał/Wojtek/Paweł D.) zmienia strukturę bez ostrzeżenia → Power Query się wywala → godziny na ręczne przepinanie i wyjaśnianie, co się zmieniło". Drugi, pełny raport całego zespołu (czerwiec-sierpień 2026, 9 osób, 1997h łącznie) **potwierdza i skaluje** ten wzorzec: sam wątek dane/pliki/aktualizacje/przepięcia to **214h w 114 wpisach**, najmocniej u Kacpra (65,5h) i Pawła (46,3h) — nadal największy pojedynczy, powtarzalny koszt operacyjny, stąd priorytet #2 zaraz po silniku walidacji.

Ten sam pełny raport ujawnia drugi koszt tej samej skali, wcześniej niepoliczony: **spotkania i koordynacja (daily/weekly/prio/bieżące) to 392,8h w 438 wpisach — ok. 20% wszystkich zalogowanych godzin zespołu**, w rzeczywistości największa pojedyncza pozycja w całym zestawieniu, przed jakimkolwiek projektem klienta. `digest_generator.py` (sekcja poniżej) adresuje to wprost — ma skracać albo częściowo zastępować spotkanie cykliczny digestem z Projectly, nie tylko podsumowywać je po fakcie. Warto potraktować to jako współpriorytet #2, nie dodatek.

Trzecie znalezisko z tego raportu to nie koszt czasu, tylko **luka w śledzeniu**: **298h czasu jest zalogowane jako wciąż "otwarte"**, z czego 265,6h u jednej osoby — część prawdopodobnie od tygodni bez zamknięcia. To potwierdza z innej strony problem opisany w `PROJECTLY-ROZWOJ.md` (brak realnej daty wykonania, nic nie wymusza domknięcia wpisu) i uzasadnia nowy, tani skrypt: `stale_time_entry_nudger.py` (sekcja M w `SKRYPTY.md`).

**Biblioteka skilli raportowo-porządkowych** (szersza niż sam Power BI — Excel, Google Sheets, dowolne źródło):

- **Wykrywanie zmian struktury źródeł** (`source_schema_watcher.py`) — pilnuje plików źródłowych, wykrywa zmianę kolumny/arkusza/typu **zanim** odświeżenie się wywali, i sam tworzy zadanie dla właściciela pliku (obieg z sekcji 4) zamiast czekać, aż ktoś odkryje awarię.
- **Kontrakt struktury danych** (`data_contract_validator.py`) — lekki, uzgodniony szablon struktury pliku źródłowego per klient/proces, walidowany automatycznie przed każdym przepięciem.
- **Triage błędów Power Query** (skill, nie tylko skrypt) — wklejony błąd M/PQ dostaje klasyfikację przyczyny i gotową poprawkę, zamiast ręcznego dochodzenia za każdym razem od zera.
- **Budowa i porządkowanie raportów poza Power BI** (`report_builder.py`, `data_tidy.py`) — te same zasady co PBI-01/PBI-02 (rezultat + kryteria akceptacji, walidacja, ślad audytowy), zastosowane do raportów Excel/Google Sheets/dokumentów, które dziś Asia robi ręcznie (Kadry, Finansowy, Dane ruchy mag, raport na stronę).
- **Newsletter** (`newsletter_drafter.py`) — cykliczny draft z materiału źródłowego (zmiany produktowe, notatki, artykuły); człowiek redaguje i wysyła. Regularna, ustrukturyzowana praca — dobry pierwszy kandydat do sprawdzenia jakości draftów AI w praktyce.
- **Podsumowania** (`digest_generator.py`, `content_summarizer.py`) — bot potrafi generować: cykliczny digest aktywności z Projectly (przed Daily/Weekly, żeby skrócić lub częściowo zastąpić spotkanie), oraz streszczenia na żądanie dowolnego długiego materiału (maile, notatki ze spotkań, raporty) do szybkiego przeglądu przez człowieka.

## 11. Intake — automatyczne tworzenie i rozdzielanie zadań z maila i innych źródeł

Dziś zadania w Projectly zakłada człowiek ręcznie. Docelowo agent **czyta wejście (mail, i pluggable inne źródła) i sam zakłada dobrze opisane zadanie**, rozdzielając je do właściwej osoby lub do własnej kolejki — analogicznie do tego, jak już rozdziela pracę między siebie a ludzi (sekcje 4-5).

```
  mail / inne źródło ──▶ email_intake_triage.py
  (Teams, CRM, formularz)      │
                                 ▼
                     klasyfikacja: typ pracy +
                     projekt/klient (słowa kluczowe:
                     INDEKA, DIVERSE, AXL, Magnapharm...)
                                 │
                     ┌───────────┴───────────┐
                     ▼                       ▼
           routing_confidence_check.py   niska pewność
           wysoka pewność                       │
                     │                          ▼
                     ▼                zadanie trafia do wspólnej
        auto-tworzy zadanie w         puli z adnotacją "do
        Projectly, przypisane do      ręcznego przypisania"
        właściwej osoby lub bota      (fail-closed, jak wszędzie indziej)
```

- **Rozdzielanie po właścicielu projektu/klienta** (`task_routing_classifier.py`): dopasowanie po słowach kluczowych i historii (np. INDEKA → Asia, Magnapharm → Kacper, Okołosprzedażowe → Karol), z domyślnym przypisaniem do bota, jeśli praca jest w pełni automatyzowalna.
- **Ten sam wzorzec dla innych źródeł** (`other_source_intake.py`) — Teams, CRM, formularz zgłoszeniowy — każde źródło to osobny adapter wpinający się w tę samą klasyfikację i routing, nie osobna logika.
- **Niska pewność klasyfikacji nie jest zgadywana** — zgodnie z zasadą fail-closed z reszty dokumentu, niepewne przypadki trafiają do wspólnej puli z adnotacją, nie są przypisywane na siłę do przypadkowej osoby.
- To domyka pętlę z sekcji 1: zadanie od początku (jego powstanie) do końca (self-review, komentarz, ewentualna eskalacja) przechodzi przez Projectly bez ręcznego zakładania na wejściu.

## 12. Harmonogram i równoległość: co jest czystym Pythonem, co dopiero czyta bot AI

**Zasada warstwowa:** nie każdy skrypt woła model AI. Zdecydowana większość pracy to zwykłe skrypty Python odpalane z Harmonogramu zadań Windows, które **pobierają dane, wstępnie je obrabiają i porządkują do ustandaryzowanego, małego formatu** (JSON/plik statusu/gotowy wpis w Projectly). Bot AI wchodzi dopiero na tym już posprzątanym wyniku — interpretuje, klasyfikuje przypadki niejednoznaczne, decyduje o akcji. To tańsze (mniej wywołań modelu), szybsze i bardziej deterministyczne niż odpalanie AI do samego pobierania i parsowania danych.

```
Warstwa 1 — Python, BEZ AI, na harmonogramie          Warstwa 2 — bot AI
┌─────────────────────────────────────┐                ┌───────────────────────┐
│ fetch (API/plik/skrzynka)            │                │ czyta już POSPRZĄTANY │
│ → parsowanie, normalizacja           │  ─────────▶    │ wynik, klasyfikuje    │
│ → reguły deterministyczne (regex,    │  (tylko gdy     │ niejednoznaczne       │
│   słowa kluczowe, proste warunki)    │   reguły nie     │ przypadki, decyduje   │
│ → zapis: status.json / task w        │   rozstrzygną)   │ o akcji, tworzy/      │
│   Projectly / plik do dalszej pracy  │                 │ aktualizuje zadania    │
└─────────────────────────────────────┘                └───────────────────────┘
```

Przykład zastosowania tej zasady: `task_routing_classifier.py` (sekcja 11) najpierw próbuje dopasować projekt/klienta prostym dopasowaniem słów kluczowych w Pythonie (INDEKA, DIVERSE, Magnapharm...) — AI jest wywoływane tylko wtedy, gdy dopasowanie po słowach kluczowych jest niejednoznaczne. Tak samo `source_schema_watcher.py` sam w sobie tylko liczy hash/diff schematu pliku — AI ocenia dopiero, czy wykryta zmiana faktycznie zepsuje raport i co dokładnie napisać właścicielowi pliku.

### Harmonogram wg częstotliwości

| Częstotliwość | Skrypty (wszystkie: Python, bez AI, chyba że zaznaczono) |
|---|---|
| **Stały proces (usługa)** | `runner_loop.py` |
| **Co 30-60 s** | `heartbeat.py`, `projectly_poller.py` |
| **Co 1-2 min** | `watchdog.py` (sprawdza heartbeat) |
| **Co 15 min** | `source_schema_watcher.py`, `pbi_service_check.py` (status odświeżenia), `email_intake_triage.py` (fetch + wstępna klasyfikacja regułowa), `other_source_intake.py`, `meta_ads_api_client.py` (odczyt statusu kampanii) |
| **Co godzinę** | `human_task_scanner.py`, `crm_sync_task.py` (odczyt), `sharepoint_sync.py` (batch synchronizacji artefaktów) |
| **Codziennie** | `digest_generator.py` (przed Daily/Weekly), `crm_report_generator.py`, `secret_scanner.py` (skan logów z całego dnia), `cost_tracker.py` (agregacja dzienna) |
| **Co 48 h** | `ad_performance_analyzer.py`, `ad_test_report.py` (cykl testowania kreatyw reklamowych — sekcja 20; osobny, częstszy cykl niż cotygodniowy przegląd biznesowy) |
| **Co tydzień** | `newsletter_drafter.py`, `mailerlite_report_analyzer.py`, `skill_improver_bot.py`, `sales_report_builder.py`, `ad_spend_report_builder.py`, `infakt_export.py`, `company_financial_report_builder.py`, `web_visibility_report_builder.py`, `weekly_business_review.py` |
| **Zdarzeniowe (nie harmonogram)** | Wszystko wywoływane w reakcji na zadanie: `risk_classifier.py`, `validator_pool.py` + walidatory, `auto_approve_yellow.py`, `bounded_red_executor.py`, `escalate_to_human.py`, `human_response_validator.py`, `continuation_task_creator.py`, `projectly_reporter.py`, `projectly_self_review.py`, `pbip_validate.py`, `report_builder.py`, `data_tidy.py`, `human_task_partial_executor.py`, `human_task_briefing.py`, `mcp_email_agent_bridge.py`, `email_draft_reviewer.py`, `ad_copy_generator.py`, `ad_set_launcher.py` |
| **Na żądanie (skille, nie harmonogram)** | `pq_error_triage`, `content_summarizer.py` |

### Równoległość — komputer dedykowany, nie do codziennej pracy

Skoro maszyna jest mocna i nie będzie używana interaktywnie na co dzień, to dwa ograniczenia z pierwotnej dokumentacji (rozdz. 7.2: *"jedno zadanie sterujące myszą i klawiaturą może działać na workerze w danym momencie"*) można rozluźnić:

- **Skrypty bez UI** (fetch/tidy/monitoring, cała warstwa 1 powyżej, walidatory, integracje API) nie rywalizują o nic i mogą biec w pełni równolegle — ograniczeniem jest tylko CPU/RAM/limity API, nie pulpit.
- **Workery sterujące UI** (Power BI Desktop Bridge + zrzuty, Playwright, automatyzacja Windows) da się rozdzielić na **kilka równoległych sesji/wirtualnych pulpitów** zamiast jednej wspólnej — np. jedna sesja dla Power BI, druga dla przeglądarki, trzecia dla CRM UI — każda z własną myszą/klawiaturą, bez konfliktu. To nadal jedno zadanie UI na sesję w danym momencie, ale sesji może być kilka naraz.
- Skoro komputer nie jest maszyną do codziennej pracy, można na nim swobodnie trzymać **dużo narzędzi deweloperskich** (kilka wersji Pythona, Tabular Editor, DAX Studio, VS Code, dodatkowe CLI) bez obawy o konflikt z czyjąś codzienną konfiguracją — inaczej niż na typowym pilotażowym "używanym komputerze" z pierwotnej dokumentacji.

## 13. Zasada: agent nie odmawia wykonania, ale ma własne zdanie

Te dwie rzeczy są celowo rozdzielone, żeby się nie zlały z fail-closed i z "czerwone zawsze do człowieka" (sekcje 3-4):

- **Nie odmawia wykonania** oznacza: w ramach dozwolonego zestawu narzędzi i zakresu zadania agent próbuje, dekomponuje, szuka rozwiązania — nie kończy pracy stwierdzeniem "nie zrobię tego", jeśli zadanie mieści się w jego uprawnieniach.
- **To nie to samo co fail-closed.** Zatrzymanie się i eskalacja z powodu braku danych, uprawnień albo pewności co do rezultatu (sekcje 3-4) to nie jest odmowa — to bezpiecznik, który zostaje bez zmian. Agent nie "przełamuje" fail-closed w imię zasady "nie odmawiam".
- **Ma swoje zdanie** oznacza: może i powinien wykonać zadanie tak, jak zostało poproszone, **i jednocześnie** zostawić komentarz z odmienną opinią, zauważonym ryzykiem albo lepszym podejściem — decyzję, czy coś zmienić, zostawia człowiekowi przy następnym zadaniu. Nie blokuje bieżącej pracy na własnej opinii.
- **Sam wymyśla usprawnienia** — to nie jest zarezerwowane dla cotygodniowego `skill_improver_bot.py`. Każdy szablon komentarza z `projectly_reporter.py` (sekcja 2) dostaje opcjonalne pole "Sugestia usprawnienia", które agent wypełnia, gdy podczas pracy zauważy powtarzalny wzorzec wart zautomatyzowania — dokładnie tak, jak to zrobiliśmy ręcznie analizując raport godzin, tylko systematycznie i na bieżąco.

## 14. Tryb rozmowy: status i uzasadnienia na żądanie

Cały dotychczasowy plan jest asynchroniczny (zadania i komentarze w Projectly). To nie wystarcza, gdy chcesz usiąść i **zapytać agenta wprost: "dlaczego zrobiłeś to tak, a nie inaczej?"** — czyli rozmawiać z nim jak z pracownikiem, nie tylko czytać jego raporty.

- To **nie jest nowy kanał komunikacji** — Projectly zostaje jedynym źródłem prawdy o zadaniach. To jest dodatkowy **tryb odczytu i rozmowy nad tymi samymi danymi**: audytem (`events.jsonl`), historią decyzji, wynikami walidatorów, kosztami.
- Warunek konieczny: cały audyt musi być zapisywany w formie, którą agent (lub inna sesja agenta) potrafi odczytać i **wytłumaczyć w naturalnym języku na żądanie**, nie tylko jako suchy log techniczny — czyli każdy wpis w `events.jsonl` powinien zawierać krótkie uzasadnienie decyzji (nie tylko "co", ale "dlaczego"), zapisane w chwili jej podjęcia, a nie rekonstruowane po fakcie.
- W praktyce: sesja rozmowy to agent z dostępem do `state_store.py`, `events.jsonl` i historii zadań w Projectly dla danego okresu/klienta/projektu, odpytywana swobodnie ("pokaż mi wszystko co zrobiłeś w INDECE w tym tygodniu i dlaczego", "czemu to zadanie poszło do mnie zamiast do Asi") — bez konieczności grzebania w Projectly ręcznie.
- To domyka pętlę statusowania: zamiast czytać dziesiątki komentarzy, pytasz bezpośrednio i dostajesz odpowiedź opartą na realnym zapisie, nie na zgadywaniu przez agenta post factum.

## 15. Podsumowania: tekst, głos, wideo — i kiedy używać czego

Domyślny format zostaje tekstowy (szablon komentarza z sekcji 2, `digest_generator.py`) — to najtańsza i najszybsza forma, wystarczająca dla większości zadań. Głos i wideo to **opcje dla wybranych, ważniejszych podsumowań**, nie domyślny format każdego raportu — inaczej sama produkcja podsumowań zje budżet czasu i pieniędzy, który miał być oszczędnością.

| Format | Kiedy | Mechanizm | Koszt względem tekstu |
|---|---|---|---|
| Tekst (domyślny) | Każde zadanie, każdy digest | Szablon komentarza, `digest_generator.py` | bazowy |
| Głos (TTS) | Cykliczny digest tygodniowy, ważniejsze podsumowania na życzenie | `digest_audio.py` — TTS nad tekstem już wygenerowanym przez `digest_generator.py`, nie od zera | niski dodatkowy koszt |
| Wideo | Na życzenie, dla dużych deliverabli (np. miesięczne podsumowanie dla klienta) | `digest_video.py` — narracja TTS nad prezentacją/dashboardem, montaż | najwyższy koszt i czas generowania — używać selektywnie |

## 16. Cykliczny retro-audyt: ponowna ewidencja i diagnoza w Projectly

Analiza raportu godzin, którą zrobiliśmy ręcznie (znalezienie ~175h firefightingu danych w INDECE/DIVERSE), nie powinna być jednorazowa — powinna dziać się **cyklicznie i automatycznie** nad historią zadań w samej Projectly, nie tylko nad eksportem CSV.

- **`task_retro_auditor.py`** (harmonogram: co miesiąc) — przechodzi przez zamknięte i nieudane zadania w Projectly za dany okres, robi ponowną ewidencję (ile czasu/kosztu poszło na co, wg klienta/projektu/typu pracy), diagnozuje powtarzające się wzorce porażek lub czasochłonności (tak jak wzorzec "przepięcie danych" w tej rozmowie), i proponuje konkretne automatyzacje do dopisania do `SKRYPTY.md`.
- Wynik trafia jako **zadanie do przeglądu przez człowieka** (żółte — to rekomendacja, nie automatyczna zmiana priorytetów), nie jako cichy log — żeby retro-audyt faktycznie wpływał na kolejność prac, a nie tylko leżał w pliku.
- To zamyka pętlę uczenia się całego systemu: zadania → wykonanie → audyt → retro-audyt → nowe skrypty/skille → mniej firefightingu → kolejny retro-audyt pokazuje mniejsze liczby. Bez tego mechanizmu plan wdrożenia bazuje tylko na jednorazowej analizie z sierpnia 2026, która z czasem się zdezaktualizuje.

## 17. Wyłącznik awaryjny (kill switch)

Limity kosztu per zadanie (`max_ai_cost_usd`) i logi (`cost_tracker.py`) nie są tym samym co twardy wyłącznik całego systemu. Przy integracji z Meta Ads (pieniądze), CRM (dane klientów) i mailem (reputacja), pojedynczy błąd w klasyfikacji ryzyka mógłby narobić szkód szybciej, niż limity per zadanie zdążą zareagować.

- Jeden globalny przełącznik (plik `STOP.flag` sprawdzany przez `runner_loop.py` na starcie każdej pętli, lub komenda w Projectly) zatrzymuje **wszystkie** workery, niezależnie od tego, w jakiej fazie/zadaniu są.
- Kill switch działa niezależnie od kolejki — nie czeka, aż bieżące zadanie się skończy, tylko przerywa bezpiecznie (zapisuje stan, jak w procedurze PAUSE z dokumentacji bazowej) i nie podejmuje nowych akcji do czasu ręcznego zdjęcia blokady.
- To uzupełnienie, nie zamiennik dla limitów per zadanie i klasyfikacji ryzyka — pierwsza linia obrony to nadal risk_classifier i walidatory; kill switch to ostatnia linia, na wypadek gdyby pierwsza zawiodła.

## 18. Raporty biznesowe cykliczne: sprzedaż, wydatki reklamowe, finanse, widoczność w sieci

Cztery nowe raporty cykliczne (co tydzień), agregowane w jedną cotygodniową analizę biznesową — dokładają się do biblioteki z sekcji 10, tym razem na poziomie całej firmy, nie pojedynczego klienta.

| Raport | Źródło danych | Skrypt |
|---|---|---|
| Sprzedażowy | System transakcyjny (API/MCP — mechanizm do doprecyzowania po stronie systemu) | `sales_report_builder.py` |
| Wydatki reklamowe | Meta Ads API + TikTok Ads API | `ad_spend_report_builder.py` |
| Finansowy całej firmy | System transakcyjny + inFakt (**dedykowane konto bota**, API jeśli dostępne, inaczej eksport CSV z portalu — `infakt_export.py`) | `company_financial_report_builder.py` |
| Widoczność w sieci | Google Search Console + Analytics (SEO, ruch) **oraz** social media (zasięgi, wzmianki) | `web_visibility_report_builder.py` |

**`weekly_business_review.py`** — cykliczny (co tydzień), agreguje wszystkie cztery raporty, generuje wnioski i **od razu gotowy plan wdrożenia** dla każdego z nich. Szybkość jest tu realna: analiza i rekomendacja powstają natychmiast, nie czekają na nic. To, co dzieje się z każdym wnioskiem dalej, zależy od jego klasyfikacji ryzyka — dokładnie ten sam trójstopniowy podział co reszta systemu, nie osobna ścieżka dla raportów biznesowych:

- **Zielone wnioski** (np. "ten wpis blogowy generuje najwięcej ruchu, warto zrobić podobny") — agent może od razu przygotować draft/rekomendację, bez pytania.
- **Żółte wdrożenia** (np. poprawka w raporcie, aktualizacja danych w CRM na podstawie wniosku) — przez `validator_pool.py` jak każda inna żółta akcja.
- **Czerwone wdrożenia** (zmiana budżetu, cen, strategii) — **domyślnie do człowieka jako gotowe zadanie z uzasadnieniem i planem** (sekcja 4), **chyba że mieszczą się w zdefiniowanej granicy bounded red** (sekcja 3 — np. korekta budżetu Meta Ads w ustalonych widełkach). Poza granicą — zawsze do Ciebie, nawet jeśli wniosek jest oczywisty.
- Finanse (inFakt, dane transakcyjne) **celowo nie mają na starcie żadnego bounded red** — to jedyna domena, gdzie nawet drobne, pozornie oczywiste działania zostają w 100% ręczne, dopóki nie zapadnie osobna decyzja o rozszerzeniu.

To domyka sposób, w jaki "od razu wdraża" współistnieje z "czerwone zawsze do człowieka": **szybkość jest w tempie analizy i gotowości planu, nie w pomijaniu zgody na nieodwracalne/finansowe kroki.**

## 19. Cztery AI na komputerze deva — kto ma jaką władzę

Rozbicie "co konkretnie siedzi na ekranie" pokrywa się niemal 1:1 z tym, co już zaprojektowane wcześniej pod kątem roli/ryzyka — dobry test spójności architektury z dwóch różnych kierunków.

1. **Orkiestrator (AI sterujące ekranem, "główna władza")** = `runner_loop.py` + Planner AI z dokumentacji bazowej ("AI jako planista i kontroler"). Decyduje, jakiego narzędzia użyć do danego kroku zadania — trzyma się hierarchii: API/MCP → pliki/CLI/skrypt → Claude Code (VS Code) do pracy nad kodem → automatyzacja UI/Playwright → klikanie po ekranie (computer use) jako ostatnia deska ratunku. **"Główna władza" = decyduje o strategii wykonania, nie o zatwierdzeniu ryzyka.** To zostaje przy `risk_classifier.py`/`validator_pool.py` niezależnie od tego, który sub-agent orkiestrator wybierze — inaczej "główna władza" zacząłaby znaczyć "omija fail-closed", co cofnęłoby zasady z sekcji 3-4.
2. **Claude Code w VS Code** (praca nad projektami w folderach) — właściwy wykonawca pracy deweloperskiej: otwiera repo, edytuje pliki, testuje, commituje na gałęzi. To realnie duża część pracy bota-dev (Krzysztof w `ZESPOL-BOTOW.md`). Subskrypcja vs API mają różny profil ryzyka przy pracy 24/7: subskrypcja ma limity okresowe pomyślane pod człowieka pracującego z przerwami — przy ciągłym automatycznym obciążeniu realne ryzyko to zatrzymanie się w połowie zadania po wyczerpaniu limitu okna czasowego. API rozlicza się ściśle za zużycie, bez takiego sufitu. Rekomendacja: API dla runnera (zgodnie z resztą planu), subskrypcja zostaje na komputerze-warsztacie do pracy interaktywnej (`ZESPOL-BOTOW.md` sekcja 4) — i **przetestować to empirycznie** przed oparciem całodobowej pracy na limicie subskrypcji.
3. **AI w przeglądarce (rozszerzenie Anthropica w Chrome)** — to nie to samo co Playwright już zaplanowany w `meta_ads_ui_fallback.py`/browser worker. Rozszerzenie to narzędzie ad-hoc do pojedynczych, nieprzewidzianych zadań, dla których nie ma jeszcze skryptu. Dla zadań powtarzalnych (Meta Ads, CRM UI) zostaje Playwright — deterministyczny i w pełni audytowalny. Rozszerzenie to wyjątek w hierarchii z pkt 1, nie podstawowa metoda.
4. **Walidator błędów klikający po ekranie, sprawdzający czy praca idzie do przodu** = `validator_visual.py` (`vision_reviewer.py`) z `SKRYPTY.md` kategorii C, część `validator_pool.py`. To już istnieje w planie pod inną nazwą.

## 20. Cykl testowania kreatyw reklamowych — Meta i TikTok, co 48h

Główny zmierzony ból w reklamach: analiza, raport co 48h, dobre teksty w wielu wariantach, test i weryfikacja co dwa dni. To osobny, częstszy cykl niż cotygodniowy `weekly_business_review.py` (sekcja 18) — tamten to strategiczny przegląd całej firmy, ten to taktyczna pętla testowa dla aktywnych kreatyw.

```
ad_copy_generator.py ──▶ ad_set_launcher.py ──▶ (2 dni działania) ──▶ ad_performance_analyzer.py ──▶ ad_test_report.py
(warianty z person          (bounded_red:                                (CTR/CPC/CPA,                (raport + zadania
 kupujących, zielone)        budżet testowy                                bez AI, czyste                follow-up: pauza
                             na wariant)                                   liczenie)                     lub skalowanie)
```

- **`ad_copy_generator.py`** — generuje wiele wariantów tekstu reklamowego (nagłówek, treść, CTA), dopasowanych do konkretnych buyer person z `persony-sprzedaz/persony-odczaruj.md` / `persony-clickless.md` (już wgrane wcześniej w tej rozmowie) — nie ten sam tekst przeformułowany, tylko realnie różne kąty per segment. Zielone: to draft, nic jeszcze nie kosztuje.
- **`ad_set_launcher.py`** — uruchamia wariant jako mały test na Meta/TikTok. To **nowy typ bounded red: `ad_test_launch`** (sekcja 3) — autonomicznie tylko w ramach jawnie ustawionej granicy (budżet dzienny na wariant × maks. liczba równoległych wariantów), którą Ty ustawiasz w `approval_policy.yaml`, nie bot. Bez ustawionej granicy — zwykłe czerwone, jak wszędzie.
- **`ad_performance_analyzer.py`** — co 48h liczy CTR/CPC/CPA per wariant, czysty Python bez AI (sekcja 12 — to jest liczenie, nie ocena). Klasyfikuje: `pause_candidate` (0 konwersji przy sensownym wydatku), `scale_candidate` (najlepsze CPA), `keep_testing` (za wcześnie albo średnio).
- **`ad_test_report.py`** — publikuje raport w Projectly i **od razu** tworzy zadania follow-up, każde z właściwym poziomem ryzyka:
  - Wariant do wstrzymania → zadanie typu `ad_variant_pause` (**żółte** — ograniczenie wydatku jest z natury bezpieczniejsze niż jego zwiększenie, więc nie wymaga Twojej zgody za każdym razem).
  - Wariant do skalowania → zadanie dla Ciebie, `budget_change` (**czerwone** — to realne przesunięcie budżetu, zawsze Twoja decyzja, niezależnie jak oczywisty wygląda wynik).
- To domyka pętlę z sekcji 18 ("szybkość jest w tempie analizy, nie w pomijaniu zgody"): agent samodzielnie testuje, liczy i rekomenduje co 48h; Ty klikasz tylko przy realnym przesunięciu pieniędzy, nie przy każdym teście.

## 21. Cotygodniowy raport z maili MailerLite

Osobny raport od newslettera (`newsletter_drafter.py`, sekcja 10, który *tworzy* treść) — ten *analizuje* to, co już zostało wysłane w danym tygodniu: teksty, tytuły, czytelność, klikalność, i docelowo wygląd.

- **`mailerlite_client.py`** — konektor do MailerLite REST API (kampanie + statystyki, potwierdzone jako w pełni dostępne przez API — sekcja 6/`integrations.yaml`).
- **`mailerlite_report_analyzer.py`** (harmonogram: co tydzień) — dla każdej kampanii wysłanej w ostatnich 7 dniach liczy:
  - **Statystyki** (zielone, czysty Python): open rate, CTR, click-to-open rate.
  - **Czytelność tekstu** (zielone, czysty Python, heurystyka): średnia długość zdania, najdłuższe zdanie — sygnał typu "ściana tekstu", nie certyfikowany indeks dla języka polskiego.
  - **Ocena tonu i tytułu** (wymaga modelu — jeśli brak klucza API, raport jasno to zaznacza zamiast zmyślać opinię, ten sam wzorzec fail-closed co `validator_visual.py`).
  - **Ocena wyglądu maila** — **celowo jeszcze nie zaimplementowana**. Wymaga wyrenderowania HTML maila do obrazu (Playwright — dopisany do `requirements.txt` jako kolejna warstwa) i przepuszczenia przez ten sam walidator wizualny co zrzuty Power BI. Do dodania, gdy Playwright trafi do pilotażu.
- Raport trafia jako komentarz w Projectly (zielone — to analiza, nic nie wykonuje) — jeśli z raportu wynika konkretna rekomendacja zmiany (np. "skróć zdania", "zmień porę wysyłki"), to trafia jako zwykłe zadanie żółte/czerwone zależnie od tego, co konkretnie miałoby się zmienić, nie automatycznie z tego raportu.
