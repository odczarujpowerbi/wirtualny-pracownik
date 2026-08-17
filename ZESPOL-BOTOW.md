# Zespół botów-pracowników — architektura wieloosobowa

Rozwinięcie architektury z `PLAN-WDROZENIA.md` (jeden wirtualny pracownik) na **zespół**: każdy bot to osobna rola/osoba w Projectly, zwykle na osobnym komputerze, z własnym zestawem umiejętności — dokładnie faza E "Platforma zespołowa" z mapy rozwoju dokumentacji bazowej (rozdz. 17: *"MCP, panel, helpdesk, marketing, media — warunek: Control plane, RBAC, monitoring i SLA"*), teraz rozpisana szczegółowo. Wszystko z `PLAN-WDROZENIA.md` (silnik walidacji, fail-closed, czerwone/żółte/zielone, bounded red, kill switch) obowiązuje **każdą** rolę bez wyjątku — ten dokument dokłada tylko warstwę wieloosobową na wierzchu.

## 0. Rola człowieka w zoskryptowanej firmie

Im dalej ten plan idzie, tym ważniejsze jest jasno powiedzieć, co **zostaje** po stronie człowieka — nie jako ograniczenie techniczne "jeszcze tego nie umiemy", tylko jako świadoma granica architektury. Trzy rzeczy są zarezerwowane dla ludzi z definicji, nie z braku możliwości:

1. **Decyzje czerwone i strategiczne.** Budżet, ceny, strategia, rekrutacja, narzędzia rozwojowe. Agent strategiczny (sekcja 2) agreguje dane i proponuje kierunki, ale wybór zawsze należy do prezesa — to nie jest limit dzisiejszej technologii, to definicja tego, co znaczy zarządzać firmą.
2. **Źródło nowych procedur.** Ktoś musi zrobić coś po raz pierwszy, żeby dało się to zaproceduralizować i przekazać botowi (patrz "warsztat" — sekcja 4). W pełni zoskryptowanej firmie praca ludzi przesuwa się z wykonywania powtarzalnych rzeczy na robienie nowych, nieprzewidzianych rzeczy i zamienianie ich w skille/procedury po 2-3 powtórzeniach. Im lepsza automatyzacja, tym **cenniejsza**, nie mniej potrzebna, staje się ta rola.
3. **Relacje, w których zaufanie jest produktem.** Rozmowy z klientami i szkolenie ludzi to transfer zaufania człowiek-człowiek, nie transfer informacji — bot może przygotować materiał czy briefing (`human_task_briefing.py`), ale nie zastąpi człowieka w samej rozmowie.

**Spotkania zespołu maleją liczebnie wraz z mniejszym zespołem, ale zmieniają charakter** — status/Daily/Weekly w dużej mierze zastępuje już digest i tryb rozmowy (`PLAN-WDROZENIA.md` sekcje 14/16); to, co zostaje, to mentoring, decyzje i rozmowy z klientami — czyli dokładnie te trzy kategorie powyżej, nie raportowanie statusu.

**Metryka warta śledzenia:** obok istniejącego KPI "Ręczne zatwierdzenia / 100 zadań" (`PLAN-WDROZENIA.md` sekcja 8, który powinien maleć — to sygnał przecieku rutyny do ludzi), warto dodać drugi, odwrotny: **godziny człowieka wg kategorii (decyzje czerwone / tworzenie nowych procedur / relacje)** — ten powinien zostać stabilny albo rosnąć w wartości, nawet gdy całkowita liczba godzin ludzkich maleje. Spadek pierwszego KPI przy stabilnym drugim to dowód, że automatyzacja działa tak, jak powinna — nie że ludzie stają się zbędni.

## 1. Zasada: jeden komputer = jeden pracownik = jedna rola w Projectly

| Rola (przykład) | Odpowiedzialność | Umiejętności/skille |
|---|---|---|
| Waldek | Marketing i sprzedaż | Meta Ads, CRM, newsletter, raport widoczności w sieci, raport sprzedażowy |
| Krzysztof | Developer | Power BI (PBI-01/02), git/dev tools, INDEKA/DIVERSE — firefighting danych |
| Zofia | Asystentka prezesa | Digesty/podsumowania, przygotowywanie opracowań, tryb rozmowy z Pawłem |
| Zenek | Administracja | Microsoft Graph (konta, licencje), SharePoint, Kadry/HR — operacje na listach |
| Strateg | Analiza całej firmy, rekomendacje dla prezesa | Czyta wszystko (cross-role), nie wykonuje zadań operacyjnych |
| Operator floty | Bieżące zarządzanie pracą wszystkich agentów naraz, nadawanie kierunku, przegląd eskalacji | Czyta status na żywo i kolejki wszystkich ról (`PLAN-WDROZENIA.md` sekcja 2), nie wykonuje zadań operacyjnych — patrz sekcja 1a |
| Paweł | Prezes — decyzje strategiczne i czerwone | — (człowiek) |

Każda rola w Projectly to osobne przypisanie, dokładnie tak jak przy ludziach (Asia/Kacper/Karol dziś). `task_routing_classifier.py` (`PLAN-WDROZENIA.md` sekcja 11) rozszerza się o routing do **konkretnej roli-bota**, nie tylko "bot ogólny vs człowiek" — to jest jedyna zmiana w istniejącym mechanizmie intake, reszta działa bez zmian.

## 1a. Operator floty — rola człowieka, nie bota, na później

W odróżnieniu od reszty tabeli to jest **stanowisko dla człowieka**, nie kolejny bot — i celowo odłożone w czasie, nie do obsadzenia teraz.

- **Co robi:** ogląda `live_status_publisher.py` (`PLAN-WDROZENIA.md` sekcja 2) i kolejki eskalacji wszystkich ról naraz, zarządza priorytetami bieżącej pracy, przekierowuje uwagę agentów tam, gdzie akurat potrzeba — codzienna operacyjna koordynacja floty, nie strategia firmy.
- **Czym się różni od Stratega:** Strateg (bot, sekcja 2 wyżej) analizuje dane i rekomenduje kierunek prezesowi raz w tygodniu — strategia firmy, nie codzienna operacja. Operator floty to bieżące, godzina-po-godzinie zarządzanie kolejkami i priorytetami — operacyjne, nie strategiczne.
- **Czym się różni od Pawła:** Operator floty triażuje i porządkuje kolejkę eskalacji, ale **nie przejmuje autorytetu decyzyjnego** nad czerwonymi/strategicznymi sprawami — te nadal trafiają do właściwego właściciela procesu albo do Pawła, zgodnie z zasadami z `PLAN-WDROZENIA.md` sekcji 3-4. Operator floty to dyspozytor, nie ostateczny zatwierdzający.
- **Kiedy to obsadzić:** dopiero gdy istnieje więcej niż jedna rola-bot do nadzorowania (czyli po co najmniej dwóch stabilnych wdrożeniach z sekcji 5). Przy jednym pracowniku Paweł sam jest naturalnym operatorem — dodanie tej roli wcześniej byłoby stanowiskiem bez pracy do wykonania.

## 2. Agent strategiczny: pełny wgląd, zero własnej egzekucji operacyjnej

- **Czyta (zielone, tylko odczyt):** wszystkie `weekly_business_review` (sekcja 18), status i historię zadań każdej roli, wszystkie `task_retro_auditor.py` (sekcja 16).
- **Cel:** raz w tygodniu (lub na żądanie) przygotowuje dla prezesa rekomendację kierunku działań — **zawsze jako dokument/zadanie do przeglądu przez człowieka, nigdy nie wdraża strategii sam.** To jest bardziej "czerwone niż czerwone": strategia firmy nie ma i nie będzie miała bounded red (w odróżnieniu od np. budżetu Ads) — nie ma widełek, w których agent decyduje sam o kierunku firmy.
- **Może autonomicznie zlecać zadania innym rolom-botom** (np. "Krzysztof, zbadaj czy da się zautomatyzować X — widzę to jako powtarzający się wzorzec w retro-audycie"). To nowy sposób powstawania zadań w Projectly, obok: człowiek ręcznie, intake z maila (sekcja 11), inne źródła.
- **Zastrzeżenie bezpieczeństwa, nienegocjowalne:** zlecenie zadania przez Stratega **nie omija klasyfikacji ryzyka wykonawcy**. Jeśli Strateg zleci Waldkowi "zwiększ budżet kampanii o 50%", to zadanie i tak przechodzi przez `risk_classifier.py` i bounded red Waldka jak każde inne — Strateg deleguje pracę, nie uprawnienia. Delegacja bot-do-bota to nowe *źródło* zadania, nie nowa *ścieżka* omijająca walidację.

## 3. Boty rozmawiają ze sobą jak zespół

- Rozszerzenie trybu rozmowy (`PLAN-WDROZENIA.md` sekcja 14) na komunikację bot-bot: rola może zapytać inną rolę o kontekst potrzebny do własnej pracy (np. Krzysztof pyta Waldka, jakie dane wejściowe ma raport reklamowy, zanim zbuduje integrację po jego stronie).
- Mechanizm: każda rola ma dostęp do audytu/stanu innej roli (ten sam `audit_query.py` z sekcji 14, tylko wywoływany bot-do-bota) plus możliwość zostawienia pytania/komentarza na zadaniu drugiej roli w Projectly — dokładnie tak, jak zrobiłby to człowiek.
- To wymiana informacji i kontekstu (zielone) — "spotkanie" dwóch botów kończy się co najwyżej wnioskiem, nigdy auto-zatwierdzeniem czerwonej akcji jednej z nich. Rozmowa nie jest furtką obok risk_classifiera.

## 4. Dystrybucja skilli: jeden warsztat, wielu pracowników

- Paweł rozwija i dopracowuje skille na **jednym, centralnym komputerze** ("warsztat"), wrzuca gotowe wersje do folderu na OneDrive (np. `AI Worker/Skills/<nazwa-skilla>/`).
- Każdy komputer-pracownik ma `skill_sync_puller.py` (harmonogram: co godzinę/codziennie) — sprawdza folder OneDrive, pobiera nowe/zaktualizowane skille pasujące do swojej roli, przeładowuje lokalny `skill_registry.py`.
- Każda rola ma też **własny** `skill_improver_bot.py` (`PLAN-WDROZENIA.md` sekcja 8), sugerujący poprawki wyłącznie do swoich skilli na podstawie własnych logów użycia — nie miesza się w skille innych ról.
- **Aktualizacja wiedzy na żądanie przez Projectly:** nowy typ zadania `knowledge_update` — Paweł pisze zadanie przypisane do konkretnej roli z instrukcją ("zaktualizuj się o zmianę procesu X"), bot odbiera je przez swój zwykły poller jak każde inne zadanie, aktualizuje lokalną wiedzę/config/skill, potwierdza komentarzem. Żaden nowy kanał komunikacji — to naturalne rozszerzenie istniejącego przepływu zadań (sekcja 2), tylko nowy typ zadania.

## 5. Kolejność wdrożenia — jedna rola na raz, nie wszystkie naraz

1. **Najpierw jeden pracownik** — Krzysztof-dev, bo tam jest największy zmierzony ból (INDEKA/DIVERSE, ~175h z analizy raportu godzin). Cały pipeline z `PLAN-WDROZENIA.md` działający na produkcji na jednym komputerze, bez wyjątków.
2. Dopiero po potwierdzeniu stabilności (kryteria odbioru z dokumentacji bazowej, rozdz. 13) — **drugi** komputer/rola, np. Waldek-marketing, z własnym `skill_sync_puller.py` i zestawem skilli.
3. Zofia i Zenek dochodzą kolejno, każdy dopiero gdy poprzednia rola pracuje bez interwencji przez ustalony okres.
4. **Agent strategiczny na końcu** — potrzebuje realnych danych z co najmniej 2-3 ról i kilku tygodni retro-audytów, żeby jego rekomendacje miały jakąkolwiek wartość. Uruchomienie go pierwszego dnia oznaczałoby doradzanie prezesowi na podstawie niczego.

## 6. Nowe skrypty

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `role_registry.py` | Rejestr ról-botów w Projectly (Waldek, Krzysztof, Zofia, Zenek, Strateg...) z przypisanym komputerem i zestawem skilli | Wczytywany przy starcie runnera na każdym komputerze | infra |
| `task_routing_classifier.py` (rozszerzenie) | Routing zadania nie tylko bot/człowiek, ale do konkretnej roli wg typu pracy | Po utworzeniu zadania (intake, człowiek, inna rola) | infra |
| `strategic_agent_review.py` | Agreguje `weekly_business_review` i retro-audyty wszystkich ról, przygotowuje rekomendację kierunku dla prezesa | Harmonogram, co tydzień | zielone (analiza) → rekomendacja zawsze do człowieka |
| `bot_task_delegation.py` | Tworzy zadanie dla innej roli-bota (np. przez Stratega); nie omija `risk_classifier.py` wykonawcy | Zdarzeniowe, gdy rola uzna że praca należy do innej roli | zielone (samo utworzenie zadania) |
| `bot_to_bot_consult.py` | Zadaje pytanie/prosi o kontekst inną rolę, czyta jej audyt/stan przez `audit_query.py` | Zdarzeniowe, w trakcie planowania zadania | zielone |
| `skill_sync_puller.py` | Sprawdza folder skilli na OneDrive, pobiera nowe/zaktualizowane wersje pasujące do roli, przeładowuje `skill_registry.py` | Harmonogram, co godzinę/codziennie, per komputer | infra |
| `knowledge_update_handler.py` | Odbiera zadanie typu `knowledge_update` z Projectly, aktualizuje lokalną wiedzę/config/skill, potwierdza komentarzem | Zdarzeniowe, gdy poller odbierze zadanie tego typu | żółte |
