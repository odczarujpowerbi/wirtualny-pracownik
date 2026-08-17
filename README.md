# Wirtualny pracownik AI

Wirtualny pracownik działający niezależnie od laptopów zespołu: cyklicznie pobiera zadania, uruchamia skrypty, obsługuje aplikacje webowe i desktopowe (w tym Power BI), waliduje wyniki i zostawia pełny ślad audytowy.

> **Status:** folder tymczasowy w repo `szkolenia-powerbi` — docelowo projekt zostanie przeniesiony do osobnego repozytorium (`odczarujpowerbi/wirtualny-pracownik`), gdy integracja GitHub uzyska uprawnienia do tworzenia nowych repozytoriów.
>
> Pełna dokumentacja koncepcyjna (biznesowa i techniczna, v1.0, 6 sierpnia 2026): `Wirtualny_Pracownik_AI_Dokumentacja_Biznesowa_i_Techniczna.pdf` (przekazana przez właściciela projektu, nie dołączona do repo).
>
> Rozwinięcie o konkretne narzędzia (Projectly, CRM, Meta Ads, Google/SharePoint, e-mail przez MCP, skille) — patrz **[PLAN-WDROZENIA.md](./PLAN-WDROZENIA.md)** (architektura, silnik auto-zatwierdzania, komunikacja) i **[SKRYPTY.md](./SKRYPTY.md)** (katalog skryptów do zaimplementowania).
>
> Docelowo to nie jeden bot, tylko **zespół botów-ról** (Waldek-marketing, Krzysztof-developer, Zofia-asystentka, Zenek-administracja, Strateg) na osobnych komputerach — patrz **[ZESPOL-BOTOW.md](./ZESPOL-BOTOW.md)**. To faza E z mapy rozwoju, budowana dopiero po ustabilizowaniu jednego pracownika.
>
> **[app/](./app/)** — działający, przetestowany szkielet kodu Fazy 0-1 (nie dokumentacja): runner, klasyfikacja ryzyka, routing zadań, stan, heartbeat, kill switch. Uruchamialny lokalnie bez żadnych kluczy API (tryb mock). Zobacz `app/README.md` co działa, a czego celowo brakuje (prawdziwe Projectly, walidatory, workery).

## Rekomendacja: pilotaż najpierw

Rozpocząć od 2–4 tygodniowego pilotażu na jednym, używanym komputerze z Windows, zamiast budować od razu pełną platformę. Dopiero po potwierdzeniu powtarzalności rozdzielać system na wyspecjalizowane workery i nadawać szersze uprawnienia.

## Stack (wersja podstawowa – pilotaż)

- **System:** Windows 11 Pro, stały dostęp do zasilania i internetu, dedykowany komputer (nie do codziennej pracy).
- **Runner / AI:** Python + Harmonogram zadań Windows; Anthropic API jako główna pętla agenta (limit pilotażowy 20 USD), OpenRouter jako fallback modeli.
- **Wykonanie zadań:** PowerShell 7, Git, Power BI Desktop (PBIP/PBIR/TMDL) + Desktop Bridge, Playwright + automatyzacja Windows UI.
- **Kolejka zadań i komunikacja:** **Projectly** (własna apka do zadań, API + MCP) — jedyne źródło prawdy o statusie i historii pracy bota; zastępuje generyczną kolejkę folderową z pierwotnej koncepcji. Szczegóły w [PLAN-WDROZENIA.md](./PLAN-WDROZENIA.md).
- **Audyt:** `status.json`, `events.jsonl`, screenshoty, logi stdout/stderr, `costs.json`, raport końcowy — osobny folder per zadanie (`TASK-000142\...`), dodatkowo komentarz-podsumowanie w Projectly.
- **Zdalny dostęp:** Tailscale + Pulpit zdalny (bez publikowania RDP do internetu).
- **Integracje docelowe:** CRM (MCP), Meta Ads (API + Playwright fallback), Google Workspace, SharePoint (Graph API), e-mail przez dedykowanego agenta (MCP), Power BI (jak niżej), narzędzia developerskie, system transakcyjny (sprzedaż), inFakt (księgowość — dedykowane konto bota), Google Search Console/Analytics + social media (widoczność w sieci).
- **Repozytoria:** kod i PBIP wersjonowane w GitHubie, poza folderem synchronizowanym przez OneDrive; agent nie zapisuje bezpośrednio do `main` — zawsze branch + pull request do akceptacji.

## Kluczowe zasady

- AI planuje, interpretuje i ocenia rezultat; skrypty i dedykowane narzędzia wykonują powtarzalne czynności. Klikanie po ekranie dopiero, gdy brak stabilnego API/CLI.
- Hierarchia metod wykonania: **1. API/MCP → 2. pliki/CLI/skrypt → 3. automatyzacja UI → 4. computer use (screenshoty)**.
- Zasada fail closed: przy niepewności co do aplikacji/konta/rezultatu agent nie wykonuje działania nieodwracalnego — zapisuje stan i prosi o decyzję.
- Klasyfikacja działań: **zielone** (odczyt, automatycznie) / **żółte** (zmiana, automatycznie w granicach polityki — auto-zatwierdzane przez pulę niezależnych walidatorów, patrz [PLAN-WDROZENIA.md](./PLAN-WDROZENIA.md) sekcja 3) / **czerwone** (publikacja, budżet, dane — zawsze trafia do człowieka jako zadanie, niezależnie od walidatorów).
- Sekrety nigdy w repo/logach/screenshotach; maskowanie pól password/token/api_key/authorization/cookie.
- Bot sam ocenia własny rezultat względem kryteriów zadania (self-review) i dopisuje komentarz w Projectly, zanim (jeśli trzeba) utworzy zadanie dla człowieka.
- Domyślnie agent radzi sobie sam. Eskalacja do człowieka to wyjątek: pełny obieg zadanie → komentarz człowieka → weryfikacja odpowiedzi → kontynuacja agenta (sekcja 4 planu), plus bot cyklicznie zagląda w zadania ludzi i wykonuje ich automatyzowalną część lub przygotowuje im opracowanie (sekcja 5 planu).
- Agent nie odmawia wykonania w ramach swoich uprawnień, ale ma własne zdanie: wykonuje zadanie i dopisuje odmienną opinię/sugestię usprawnienia obok, zamiast blokować pracę na własnej ocenie (sekcja 13 planu). Da się z nim też porozmawiać na żądanie — zapytać "dlaczego zrobiłeś tak, a nie inaczej" i dostać odpowiedź opartą na realnym audycie, nie na zgadywaniu (sekcja 14).
- **Uwaga kosztowa:** cel "bardzo tani pracownik" wymaga kalibracji liczby walidatorów pod kątem historii sukcesu zadania (sekcja 3) — 3 walidatory na każde żółte zadanie to realny, policzalny koszt, nie tylko rygor.

## Pierwsze procesy pilotażowe

| ID | Proces | Autonomia |
|---|---|---|
| PBI-01 | Walidacja istniejącego PBIP (screenshoty stron, lista błędów, raport) | Odczyt – automatyczny |
| PBI-02 | Bezpieczna korekta raportu (gałąź, test, PR) | Zmiana – akceptacja przed merge |
| WEB-01 | Kontrola jednej aplikacji webowej (Playwright) | Odczyt – automatyczny |
| SCRIPT-01 | Uruchomienie skryptu cyklicznego | Automatyczny |
| OPS-01 | PAUSE / RESUME / przejęcie zdalne | Człowiek w pętli |

## TODO

- [ ] Wybrać konkretny komputer (min. 4 rdzenie/16 GB RAM, docelowo 32 GB przy Power BI + przeglądarka równolegle)
- [ ] Potwierdzić dostęp do Projectly API/MCP i zdefiniować kontrakt zadania (`expected_result`, `acceptance_criteria`, `risk_level_hint`)
- [ ] Skonfigurować katalogi `C:\AIWorker\` (app/repos/workspace/runs/cache/logs/secrets)
- [ ] Ustalić repo GitHub i workspace Power BI jako sandbox pilotażu
- [ ] Skonfigurować Anthropic API (limit pilotażowy) + OpenRouter jako fallback
- [ ] Zaimplementować runner + pętlę Projectly (poller → wykonanie → komentarz-raport)
- [ ] Zbudować silnik walidacji i auto-zatwierdzania żółtych akcji (`validator_pool.py`, `approval_policy.yaml`) — priorytet #1, patrz [PLAN-WDROZENIA.md](./PLAN-WDROZENIA.md)
- [ ] Zbudować skille raportowe/porządkujące dane (`source_schema_watcher.py`, `data_contract_validator.py`, `newsletter_drafter.py`, `digest_generator.py`) — priorytet #2, oparty na realnej analizie raportu godzin (~175h firefightingu danych), patrz PLAN-WDROZENIA.md sekcja 10
- [ ] Przetestować PAUSE/RESUME i wznowienie po restarcie
- [ ] Podłączyć integracje wg kolejności z planu wdrożenia: CRM → Meta Ads → Google/SharePoint → e-mail (MCP)
- [ ] Zbudować intake z maila i innych źródeł (`email_intake_triage.py`, `task_routing_classifier.py`) — automatyczne tworzenie i rozdzielanie zadań, patrz PLAN-WDROZENIA.md sekcja 11
- [ ] Uruchomić rejestr skilli i bota ulepszającego skille (`skill_registry.py`, `skill_improver_bot.py`)
- [ ] Zbudować cotygodniowe raporty biznesowe (sprzedaż, wydatki reklamowe, finanse przez inFakt, widoczność w sieci) — dopiero po dojrzałym silniku walidacji, bo dotyka pieniędzy, patrz PLAN-WDROZENIA.md sekcja 18
- [ ] Po potwierdzeniu kryteriów odbioru: przenieść folder do docelowego repozytorium `odczarujpowerbi/wirtualny-pracownik`

## Dalsza dokumentacja

- **[PLAN-WDROZENIA.md](./PLAN-WDROZENIA.md)** — architektura komunikacji przez Projectly, silnik auto-zatwierdzania, fazy wdrożenia, integracje.
- **[SKRYPTY.md](./SKRYPTY.md)** — pełny katalog skryptów Python do zaimplementowania, z celem, wyzwalaczem i poziomem ryzyka.
- **[ZESPOL-BOTOW.md](./ZESPOL-BOTOW.md)** — docelowa architektura wieloosobowa: role-boty na osobnych komputerach, agent strategiczny, komunikacja bot-bot, dystrybucja skilli.
- **[PRZED-PILOTAZEM.md](./PRZED-PILOTAZEM.md)** — checklist otwartych decyzji do zamknięcia przed startem (rejestr D-01..D-07, RODO, zespół, backup, dostępy) i przypomnienie realnego zakresu pilotażu.
- **[SKALOWANIE.md](./SKALOWANIE.md)** — jak kopiować system na inne komputery i inne firmy: rozdział rdzenia od konfiguracji, izolacja per firma, bootstrap nowego komputera, klucze per wdrożenie.
- **[INSTRUKCJA-WDROZENIA.md](./INSTRUKCJA-WDROZENIA.md)** — instruktaż krok po kroku dla osoby mało technicznej: co zainstalować, gdzie wpisać dostępy, jak uruchomić i sprawdzić, że działa. Praktyczny runbook, w odróżnieniu od dokumentów architektonicznych powyżej.
- **[WDROZENIE-VPS-TESTOWE.md](./WDROZENIE-VPS-TESTOWE.md)** — szybka ścieżka testowania na tanim VPS-ie z Linuksem, zanim dojedzie docelowy komputer; ten sam kod, testowany w tej sesji na Linuksie, bez kroków wymagających Power BI Desktop.
- **[PROJECTLY-ROZWOJ.md](./PROJECTLY-ROZWOJ.md)** — feedback i plan wdrożenia dla zespołu rozwijającego samą aplikację Projectly: czego dziś brakuje w API/UI (potwierdzone realnym sprawdzeniem integracji), żeby agent mógł być pełnoprawnym użytkownikiem — komentarze, data wykonania, feedback po zadaniu, relacje między zadaniami, retrospektywa.
