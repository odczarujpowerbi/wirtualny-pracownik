# Skalowanie i przenośność — inne komputery, inne firmy

`ZESPOL-BOTOW.md` opisuje wiele ról **wewnątrz jednej firmy**. Ten dokument opisuje inną oś: jak ten sam system łatwo skopiować na nowy komputer (lokalny lub zdalny) i, docelowo, na inną firmę — bez przepisywania kodu. Najtaniej wprowadzić te zasady **teraz**, przed napisaniem 67 skryptów z `SKRYPTY.md` z zaszytymi na sztywno założeniami — retrofit po fakcie byłby znacznie droższy.

## 1. Dobra wiadomość: koordynacja już jest chmurowa

Cała komunikacja między komponentami idzie przez Projectly, OneDrive i API zewnętrzne — żadna część architektury nie zakłada wspólnej sieci lokalnej. **Zdalny komputer działa bez przeróbek**, o ile ma dostęp do internetu i własne poświadczenia. To efekt uboczny wcześniejszych decyzji (Projectly jako jedyne źródło prawdy, OneDrive jako magazyn skilli), nie coś, co trzeba dodawać.

## 2. Rozdział: rdzeń (engine) vs konfiguracja firmy vs stan lokalny

Trzy warstwy, które muszą zostać rozdzielone fizycznie (osobne pliki/foldery), nie tylko pojęciowo:

| Warstwa | Co zawiera | Gdzie żyje | Czy różni się między firmami |
|---|---|---|---|
| Rdzeń (engine) | `runner_loop.py`, `risk_classifier.py`, `validator_pool.py`, cała reszta `SKRYPTY.md` — logika, nie dane | Jedno repo Git, wersjonowane | Nie — identyczny kod dla każdego wdrożenia |
| Konfiguracja firmy | `approval_policy.yaml`, mapowania klient→osoba/bot w `task_routing_classifier.py`, nazwy ról z `role_registry.py`, lista integracji i kluczy | Osobny plik/pakiet konfiguracyjny per firma | Tak — to jest to, co się wymienia przy kopiowaniu |
| Stan lokalny | `events.jsonl`, `state_store.py`, cache, logi, heartbeat | Na danym komputerze | Tak — zawsze lokalne, nigdy nie kopiowane między maszynami |

Dziś `task_routing_classifier.py` (PLAN-WDROZENIA.md sekcja 11) ma częściowo zaszyte na sztywno mapowania (INDEKA → Asia, Magnapharm → Kacper) — do przeniesienia do pliku konfiguracyjnego (`clients_routing.yaml` czy podobny) przed pierwszym wdrożeniem u innej firmy.

## 3. Jedna izolowana instancja na firmę — nie multi-tenant w jednym środowisku

Kuszące jest zbudowanie jednego wspólnego systemu obsługującego wiele firm naraz. **Odradzane wprost** — głównie z powodu RODO (`PRZED-PILOTAZEM.md` punkt o zgodności prawnej): dane klienta A nie mogą dzielić audytu/kontekstu z klientem B. Zamiast tego:

- Ten sam kod (rdzeń), **osobna instancja per firma**: osobny workspace Projectly, osobne klucze API, osobny folder skilli na OneDrive, osobny `cost_tracker.py` i `kill_switch.py`.
- To też prostszy model, gdyby to kiedyś stało się usługą sprzedawaną dalej (Clickless robi to już dla klientów w innym kontekście) — "każdy klient dostaje swoją instancję", nie dzielony system z ryzykiem przecieku między klientami.

## 4. Bootstrap nowego komputera

Dziś dołączenie nowego komputera-pracownika to nieopisany, ręczny proces. Poniżej pełna specyfikacja — do zaplanowania teraz (tanie, to tylko dokumentacja), do zbudowania i przetestowania dopiero gdy realnie pojawi się drugi komputer (zgodnie z sekcją "Kiedy to robić" niżej).

### Etapy bootstrapu

**0. Warunki wstępne (raz, po stronie firmy, nie per komputer)**
- Istnieje pakiet konfiguracji firmy (`approval_policy.yaml`, `clients_routing.yaml`, wpisy `role_registry.py`) w bezpiecznym, wersjonowanym miejscu — prywatne repo Git lub OneDrive z ograniczonym dostępem, osobno od rdzenia (kodu).
- Istnieje magazyn sekretów (vault) z kluczami API per wdrożenie (sekcja 5).

**1. Przygotowanie systemu** (`bootstrap_install.ps1`, PowerShell — minimalny, jednorazowy)
- Sprawdza wersję Windows i RAM (min. 16 GB, docelowo 32 GB — dokumentacja bazowa rozdz. 4.1).
- Wyłącza uśpienie/hibernację, konfiguruje politykę logowania automatycznego.
- Tworzy dedykowane konto standardowe dla bota (osobne od konta administratora — model tożsamości z dokumentacji bazowej rozdz. 9.1).

**2. Instalacja zależności**
- Git, Python (przypięta wersja), PowerShell 7, przeglądarki Playwright, oraz narzędzia specyficzne dla roli (Power BI Desktop + Tabular Editor/DAX Studio tylko dla roli dev, nie dla marketingu/administracji).
- Klonuje rdzeń (kod, ten sam dla każdego wdrożenia) do `C:\AIWorker\app\`.

**3. Przypisanie roli** (`bootstrap_register.py`)
- Odczytuje, jaką rolę ma pełnić ten komputer (dev/marketing/admin/strateg — podane ręcznie przy instalacji albo z pliku provisioningu), zapisuje lokalnie.
- Rejestruje się w `role_registry.py` i w Projectly — od tego momentu inne boty i ludzie widzą, że ten komputer istnieje i co robi.

**4. Pobranie konfiguracji firmy**
- Ściąga `approval_policy.yaml`, `clients_routing.yaml` i resztę pakietu konfiguracyjnego z warunku wstępnego 0 — **nie** z repo rdzenia, zgodnie z rozdziałem warstw z sekcji 2.

**5. Prowizjonowanie poświadczeń**
- Pobiera z magazynu sekretów klucze API scope'owane do tego wdrożenia (sekcja 5), zapisuje w lokalnym, zaszyfrowanym magazynie (Windows Credential Manager — dokumentacja bazowa rozdz. 9.3), nigdy w plikach konfiguracyjnych ani repo.
- Uruchamia `secret_scanner.py` jako pierwszy autotest — potwierdza, że nic nie wyciekło już na tym etapie.

**6. Pobranie skilli**
- Jednorazowe, ręczne uruchomienie `skill_sync_puller.py` (`ZESPOL-BOTOW.md` sekcja 4) — pobiera skille pasujące do przypisanej roli z biblioteki na OneDrive, zanim zostanie zaplanowane cyklicznie.
- Zapisuje wersje pobranych skilli do lokalnego `skill_registry.py` (podstawa wersjonowania floty z sekcji 7).

**7. Konfiguracja harmonogramu**
- Rejestruje w Harmonogramie zadań Windows tylko te skrypty, które dotyczą przypisanej roli (`PLAN-WDROZENIA.md` sekcja 12 — np. komputer marketingowy nie potrzebuje `pbip_validate.py` w harmonogramie).
- Uruchamia `runner_loop.py` jako usługę startującą przy starcie systemu.

**8. Test dymny (smoke test)**
- Przepuszcza jedno testowe zadanie przez pełen cykl `queued → done`, sprawdza że komentarz pojawia się w Projectly, że `heartbeat.json` się aktualizuje, że `kill_switch.py` reaguje na `STOP.flag`.
- To odpowiednik scenariuszy T-01/T-07 z planu testów dokumentacji bazowej, tylko jako checklist odbioru nowej maszyny, nie całego pilotażu.

**9. Przekazanie**
- Komputer zostawia w Projectly status "gotowy" z rolą i wersjami skilli — trafia do rejestru floty (sekcja 7), Ty widzisz go w trybie rozmowy (`PLAN-WDROZENIA.md` sekcja 14) tak samo jak każdy inny komputer.

Bez tego każde nowe stanowisko to ręczna, niepowtarzalna robota administracyjna — dokładnie ten sam problem co "prowizjonowanie dostępów" z `PRZED-PILOTAZEM.md`, tylko pomnożony przez liczbę komputerów.

## 5. Klucze API per wdrożenie, nie jeden globalny

Przy wielu komputerach i firmach jeden wspólny klucz API to: wąskie gardło (współdzielony limit), brak możliwości rozliczenia kosztu per klient, i większe ryzyko przy wycieku (jeden klucz kompromituje wszystko). Klucze API — minimum per firma, docelowo per rola — skalują się razem z flotą i pozwalają realnie mierzyć koszt per wdrożenie (`cost_tracker.py`).

## 6. Pakowanie skilli: kod generyczny + konfiguracja do wypełnienia

Żeby skill zbudowany dla jednej firmy (np. `pbip_validate.py`, `source_schema_watcher.py`) dało się przenieść do innej, paczka skilla dzieli się na:

- **Logikę** (uniwersalną — jak sprawdzić PBIP, jak wykryć zmianę schematu) — bez zmian między firmami.
- **Konfigurację** (mapowania klientów, ścieżki plików, progi ryzyka specyficzne dla tej firmy) — pusty szablon do wypełnienia przy wdrożeniu.

Dzięki temu biblioteka skilli (`SKRYPTY.md`) staje się realnym produktem/IP wielokrotnego użytku, nie kodem zrośniętym z jedną firmą.

## 7. Wersjonowanie floty

Gdy komputerów/firm przybędzie, `skill_registry.py` musi wiedzieć nie tylko "jakie skille są dostępne", ale **który komputer ma którą wersję którego skilla**. Bez tego częściowy rollout (jeden komputer ze starą wersją, drugi z nową) rozjedzie się po cichu — dopisać wersję skilla do heartbeatu/statusu, żeby było to widoczne w digestach i w trybie rozmowy (`PLAN-WDROZENIA.md` sekcja 14).

## Kiedy to robić

Punkty 1-2 (rozdział warstw, izolacja per firma) — **od razu, w Fazie 0**, bo zmiana tego po napisaniu kodu jest znacznie droższa niż zaprojektowanie tego od początku. Punkty 3-7 (bootstrap, klucze per wdrożenie, pakowanie skilli, wersjonowanie floty) — dopiero gdy realnie pojawi się drugi komputer albo druga firma, nie wcześniej. Budowanie pełnej automatyzacji instalacji dla floty, która jeszcze nie istnieje, byłoby dokładnie tym rodzajem przedwczesnego skalowania, przed którym ostrzegałem przy ocenie realności całego planu.
