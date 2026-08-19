# Rozwój Projectly — moduł feedbacku i współpracy z agentem AI

Ten dokument to feedback i plan wdrożenia **dla zespołu/bota rozwijającego samą aplikację Projectly** — nie dla Wirtualnego Pracownika jako wykonawcy zadań, tylko dla tego, kto buduje narzędzie, z którego Wirtualny Pracownik (i ludzie) korzystają. Celem jest domknięcie pętli: **agent ma być normalnym użytkownikiem Projectly** (zakłada zadania, komentuje, zamyka, eskaluje), a człowiek ma mieć realną możliwość zobaczyć, co zostało zrobione, co nie, i jak dobre były szacunki — nie tylko listę rzeczy "do zrobienia".

**Metoda:** poniższa diagnoza nie jest zgadywana. Sprawdziłem realnie, czego już dziś potrafi (i czego nie potrafi) warstwa integracyjna Projectly, do której ma dostęp agent AI — wywołując `list_projects`, `get_project_tasks`, `get_project_summary` na prawdziwych, produkcyjnych danych (m.in. projekt "Usprawnienia", 24 zadania) oraz przeglądając pełną listę dostępnych narzędzi integracyjnych. Każdy punkt niżej jest oznaczony jako **potwierdzone** (sprawdzone wywołaniem) albo **zgłoszone przez Ciebie** (Twój opis z UI, którego stąd nie widzę).

## 0. Najważniejsze odkrycie

**W dzisiejszej integracji nie ma żadnego sposobu na odczyt ani dodanie komentarza do zadania.** Sprawdziłem pełną listę dostępnych operacji (zadania, dokumentacja, wiedza, projekty) — jest tworzenie/edycja zadań, dokumentacji i przeszukiwanie bazy wiedzy, ale nic dla komentarzy.

To jest problem, bo **cała architektura Wirtualnego Pracownika (`PLAN-WDROZENIA.md`) zakłada, że komentarz w Projectly to główny i jedyny kanał komunikacji** — agent zostawia tam podsumowanie wykonania, człowiek odpowiada "zatwierdzam/popraw", agent tę odpowiedź parsuje i kontynuuje. Bez odczytu/zapisu komentarzy przez integrację **ten mechanizm nie może zadziałać na produkcji**, niezależnie od tego, jak dobrze jest napisany kod po stronie agenta (`app/escalation.py` już to zakłada). To pozycja #1 na liście priorytetów niżej.

**Aktualizacja:** wg informacji przekazanej ustnie, poprawki do komentowania zadań w Projectly zostały już wdrożone. Sprawdziłem ponownie w tej sesji pełną listę narzędzi integracyjnych dostępnych stąd (10 pozycji: zadania, dokumentacja, wiedza, projekty) — nadal nie widzę wśród nich niczego do komentarzy. To może oznaczać, że zmiana jest po stronie samej aplikacji Projectly, ale jeszcze nie dotarła do warstwy integracyjnej, z której korzysta agent (albo dotarła do innej warstwy niż ta, którą stąd widzę). Kod po stronie agenta (`app/projectly_client.py::post_comment/get_comments`, oraz nowe `task_feedback_requester.py`) jest już gotowy na podłączenie — wystarczy potwierdzić dokładny mechanizm/endpoint i zastąpić `NotImplementedError` realnym wywołaniem, bez zmiany reszty pipeline'u.

## 1. Diagnoza — potwierdzone braki w danych o zadaniu

Sprawdziłem 5 realnych, zamkniętych zadań w projekcie "Usprawnienia". Żadne z nich nie ma wypełnionego `description`, `goal` ani `effect` mimo statusu "done" — te pola są planistyczne (co i po co zrobić), nie sprawozdawcze (co realnie wyszło). Statystyki projektu (`taskStats`) sumują tylko `totalEstimatedHours` — nie ma nigdzie realnego czasu wykonania.

| # | Brak | Status | Konsekwencja dla agenta / człowieka |
|---|---|---|---|
| 1 | Komentarze do zadań (odczyt + zapis) | **potwierdzone** — brak w integracji w ogóle | Agent nie może prowadzić dialogu wykonanie→decyzja→kontynuacja opisanego w planie wdrożenia |
| 2 | Pole "data wykonania" (`completedAt`), osobne od `dueDate` (termin) | **potwierdzone** — zadanie ma tylko `dueDate` | Nie da się policzyć, kiedy coś **naprawdę** się skończyło, tylko kiedy miało się skończyć |
| 3 | Filtrowanie/sortowanie po dacie wykonania | **potwierdzone** — filtry to tylko: status, priorytet, osoba, etap | Analiza "co zrobiliśmy w tym tygodniu" musi dziś polegać na `dueDate`, czyli na planie, nie na faktach |
| 4 | Filtrowanie po statusie w zakładce Zadania (UI) | **zgłoszone przez Ciebie** — API to obsługuje, interfejs najwyraźniej nie | Szybka poprawka względem reszty — logika po stronie API już istnieje |
| 5 | Pole "feedback po wykonaniu" | **potwierdzone** — brak dedykowanego pola, `description/goal/effect` puste w realnych "done" | Nie ma miejsca, gdzie wykonawca (człowiek albo agent) opisuje, co faktycznie wyszło |
| 6 | Rzeczywisty czas pracy (`actualHours`) obok estymacji | **potwierdzone** — jest tylko `estimatedHours` | Nie da się nigdy skalibrować estymacji, bo nie ma z czym porównać |
| 7 | Relacja nadrzędne/podrzędne (podzadania) | **potwierdzone** — brak `parentTaskId`/listy podzadań w schemacie | Nie da się rozbić zadania i pokazać, że część została zrobiona |
| 8 | Relacja "zadania powiązane" (eskalacja / kontynuacja / blokuje / duplikat) | **potwierdzone** — brak w schemacie | Wątek: zadanie → eskalacja do człowieka → zadanie kontynuacji to dziś trzy osobne, nic ich nie łączy |
| 9 | Pole "blokery" | **potwierdzone** — brak | Nie ma ustrukturyzowanego miejsca na "czekam na X" |
| 10 | Klikalne odnośniki między zadaniami w treści | **zgłoszone przez Ciebie** | Pochodna punktu 7-8 — lepiej rozwiązać przez pole relacji niż parsowanie tekstu (patrz sekcja 4) |
| 11 | Zakładka/widok analizy zadań zamkniętych (co zrobione, co nie, co z tego powstało) | **zgłoszone przez Ciebie**, spójne z brakiem pól 2, 5, 7, 8 | Dziś zadanie kończy się na statusie "zamknięte" i nic więcej się z nim nie dzieje |
| 12 | Rozróżnienie "kto wykonał: człowiek / agent" w widokach | **częściowo istnieje** — w systemie jest już osoba "BOT AI" jako zwykły przypisany użytkownik, ale UI nigdzie tego nie wyróżnia | Przy jednym bocie to kosmetyka; przy kilku botach-rolach (`ZESPOL-BOTOW.md`) będzie potrzebne do czytelności |

Dodatkowa niejasność do wyjaśnienia z zespołem Projectly: API zna tylko trzy statusy zadania (`todo`, `in_progress`, `done`) — jeśli w UI istnieje osobny stan "zamknięte" różny od "done", to dziś **nie jest widoczny przez integrację** i trzeba ustalić, czy to synonim, czy realnie osobny stan.

## 2. Po co to jest agentowi AI — nie "ładne dodatki", tylko zależności

Każdy z planowanych mechanizmów Wirtualnego Pracownika (`PLAN-WDROZENIA.md`) wprost zakłada dane, których dziś nie da się zapisać:

- **Pętla eskalacji** (`app/escalation.py`, sekcja 4 planu) — tworzy zadanie dla człowieka, czyta jego odpowiedź jako decyzję, tworzy zadanie kontynuacji. Wymaga: komentarzy (odczyt decyzji) + relacji między zadaniami (oryginalne → eskalacja → kontynuacja jako jeden widoczny ciąg, nie trzy przypadkowe rekordy).
- **Samoocena wyniku przez agenta** (sekcja 1 planu — agent ocenia własny rezultat względem kryteriów, zanim coś trafi do człowieka) — wymaga pola feedback/wynik, osobnego od pól planistycznych.
- **Status na żywo** (`app/live_status_publisher.py`, sekcja 2 planu — "jeden, stały, nigdy niezamykany wpis per bot-rola, nadpisywany") — dziś nie da się nawet edytować istniejącego komentarza, bo komentarzy w ogóle nie ma przez integrację.
- **Cotygodniowy digest i miesięczny retro-audyt** (`app/mailerlite_report_analyzer.py`, planowany `task_retro_auditor.py`, sekcja 16 planu) — mają czytać zamknięte zadania z danego okresu i liczyć czas/wzorce porażek. Bez `completedAt` i `actualHours` liczyliby na podstawie terminów, nie faktów — czyli dokładnie ten sam błąd, który dziś masz ręcznie w Projectly.
- **Cykl testowania reklam 48h** (`app/ad_test_report.py`) — tworzy zadania follow-up (pauza/skalowanie) i dziś nie ma jak ich powiązać z zadaniem źródłowym poza wpisaniem ID w tekście.
- **Twoja prośba o bardziej realną estymację** — niemożliwa bez pary `estimatedHours` + `actualHours` na tym samym zadaniu.

Innymi słowy: to nie jest "Projectly mogłoby też mieć fajny raport" — to jest brakujący fundament, na którym stoi już napisany kod agenta.

## 3. Proponowany zakres, priorytetyzowany

### P0 — Blokujące (bez tego architektura z PLAN-WDROZENIA.md nie działa na produkcji)

1. **Komentarze przez integrację** — odczyt listy komentarzy zadania (autor, czas, treść) + dodanie komentarza. Rozstrzygnąć najpierw: komentarze już istnieją w bazie i brakuje tylko API, czy trzeba budować mechanizm od zera.
2. **Pole `completedAt`** (data wykonania) — ustawiane automatycznie w momencie zmiany statusu na "done"/"zamknięte", ale **edytowalne ręcznie** (Twoja uwaga: chcesz móc wpisać ją z ręki, np. przy zaległym domykaniu zadań albo przy późniejszej integracji z ewidencją godzin).
3. **Filtrowanie i sortowanie po `completedAt`** w widoku zadań i w API — zakres dat "od-do", niezależny od `dueDate`, z możliwością przełączenia domyślnego widoku "wg terminu" / "wg daty wykonania".
4. **Filtrowanie po statusie w zakładce Zadania (UI)** — logika po stronie API już to obsługuje (`status` jako filtr w `get_project_tasks`), więc to głównie brakujący element interfejsu.

### P1 — Ważne dla realnej pętli feedbacku

5. **Pole `feedback`** (notatka powykonawcza) — osobne od `description`/`goal`/`effect`, wypełniane przez wykonawcę (człowieka lub agenta) przy zamknięciu zadania. To pole, w którym agent pisze np. "zadanie wykonane w 80%, reszta w podzadaniach X, Y" albo "nie udało się z powodu Z".
6. **Relacja nadrzędne/podrzędne** — `parentTaskId` na zadaniu + widoczna lista podzadań, żeby dało się rozbić zadanie i zobaczyć drzewo.
7. **Relacja "zadania powiązane"** z typem powiązania (`eskalacja`, `kontynuacja`, `blokuje`, `duplikat`) — dokładnie to, czego potrzebuje `app/escalation.py`: oryginalne zadanie, zadanie eskalacyjne i zadanie kontynuacji jako jeden połączony ciąg zamiast trzech niezależnych wpisów.
   - Rekomendacja: **ustrukturyzowane pole relacji, nie parsowanie tekstu**. Twój pomysł z "generowaniem linków w feedbacku" da się zrobić dwojako — (a) NLP wyłapujące ID w tekście i zamieniające na link, albo (b) osobne pole relacji, które agent wypełnia wprost, bo sam tworzy powiązane zadanie i zna jego ID. Opcja (b) jest tańsza, mniej podatna na błędy i łatwiejsza do analizy zbiorczej — polecam ją, a link w treści feedbacku traktować jako **wyświetlenie** tej relacji, nie jako źródło prawdy.
8. **Pole `actualHours`** obok `estimatedHours` + prosty wskaźnik odchylenia (np. "128% estymacji") na poziomie zadania i zbiorczo na poziomie projektu/etapu. To jest fundament pod Twoją prośbę o realniejsze szacunki — dopiero z tym da się zobaczyć, które typy zadań systematycznie niedoszacowujemy.
9. **Pole `blockers`** — najprościej jako lista odwołań do innych zadań (wykorzystuje mechanizm z punktu 7) plus opcjonalny wolny tekst dla blokerów zewnętrznych (np. "czekam na dostęp od klienta"), ze statusem aktywny/rozwiązany.

### P2 — Nowa zakładka/widok: "Zrobione" / "Retrospektywa"

10. Widok zadań zamkniętych, **domyślnie filtrowany i sortowany po `completedAt`**, z zakresem dat.
11. Dla każdego zadania w tym widoku: estymacja vs rzeczywisty czas, treść feedbacku, status ukończenia (w pełni / częściowo — z linkami do podzadań/kontynuacji), kto wykonał.
12. Widok zbiorczy dla wybranego okresu: % zadań w pełni wykonanych vs częściowo, ile nowych zadań powstało jako efekt uboczny (przez relację "kontynuacja"), rozkład odchylenia estymacji wg osoby/etapu/projektu.
13. To jest właśnie to źródło danych, z którego ma korzystać planowany `task_retro_auditor.py` (miesięczny retro-audyt, `PLAN-WDROZENIA.md` sekcja 16) — dziś nie miałby z czego sensownie liczyć.

### P3 — Pod przyszły zespół wielobotowy (nie teraz, ale zaplanować z myślą o tym)

14. Wizualne rozróżnienie wykonawcy człowiek/agent w widokach (np. ikona przy osobach typu bot) — przy jednym bocie to kosmetyka, przy kilku botach-rolach (`ZESPOL-BOTOW.md`: Waldek, Krzysztof, Zofia, Zenek) stanie się potrzebne do szybkiej orientacji "co zrobił który bot".
15. Rozstrzygnąć już teraz (żeby nie przepisywać potem): czy `BOT AI` (istniejąca dziś osoba w systemie) zostaje jedynym kontem dla wszystkich botów-ról, czy każda rola dostaje swoje konto — wpływa na to, jak filtrowanie "kto wykonał" ma w ogóle działać.

## 4. Czego celowo NIE proponuję teraz

- **Integracji z ewidencją godzin** — wspomniałeś, że to "pewnie potem". To osobny, większy temat, i sensownie zależy od tego, żeby `completedAt`/`actualHours` w ogóle istniały (punkty 2 i 8) — nie robić równolegle, tylko po ustabilizowaniu tych pól.
- **Automatycznego NLP-owego wykrywania odwołań do zadań w wolnym tekście** — patrz uzasadnienie przy punkcie 7: ustrukturyzowane pole relacji jest tańsze i pewniejsze, bo agent i tak zna ID zadania, które sam tworzy.
- **Zmiany modelu ról/uprawnień** w Projectly — poza zakresem tego dokumentu, nie ma potrzeby ruszać przy okazji.

## 5. Kolejność wdrożenia

1. Komentarze przez API (P0.1) — blokujące wszystko inne, rób jako pierwsze.
2. `completedAt` + filtrowanie po nim w API (P0.2-3).
3. Filtr statusu w UI zakładki Zadania (P0.4) — szybka wygrana równolegle, bo logika po stronie API już istnieje.
4. `feedback`, relacje nadrzędne/podrzędne i powiązane (P1.5-7) — razem, bo współdzielą tę samą potrzebę: model relacji między zadaniami.
5. `actualHours` + wskaźnik odchylenia estymacji (P1.8) i `blockers` (P1.9).
6. Nowa zakładka "Zrobione"/"Retrospektywa" (P2) — dopiero gdy dane z punktów 2-5 faktycznie się zbierają, inaczej widok będzie pusty/nieużyteczny.
7. Rozróżnienie człowiek/agent w UI i decyzja o kontach botów-ról (P3) — przed startem zespołu wielobotowego, nie wcześniej.

## 6. Otwarte pytania do zespołu Projectly

- Czy komentarze do zadań już istnieją w bazie danych (i brakuje tylko API), czy trzeba je budować od zera?
- Czy "zamknięte" widziane w UI to osobny stan od `done` zwracanego przez API, czy to samo pod inną nazwą?
- Czy da się (i czy warto) edytować istniejący komentarz, a nie tylko dodawać nowe — potrzebne dla mechanizmu "status na żywo" (jeden, stale nadpisywany wpis per bot), żeby nie zaśmiecać wątku dziesiątkami wpisów co minutę.
