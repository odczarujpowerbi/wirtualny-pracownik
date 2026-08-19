# Katalog skryptów Python — Wirtualny Pracownik AI

Pomysły na skrypty pogrupowane wg domeny. Każdy skrypt ma jasno określony cel, wyzwalacz i poziom ryzyka (zielone/żółte/czerwone wg `PLAN-WDROZENIA.md`). To jest lista robocza do rozbicia na zadania implementacyjne — nie gotowy kod.

**Ważne:** większość poniższych skryptów to czysty Python bez wywołania AI — pobierają dane, normalizują, stosują proste reguły deterministyczne i zapisują ustandaryzowany wynik. Bot AI wchodzi dopiero na już posprzątanym wyniku (klasyfikacja niejednoznacznych przypadków, decyzja o akcji, treść komunikatu). Konkretny harmonogram (co 15 min / co godzinę / codziennie / zdarzeniowe) i ta zasada warstwowa są opisane w `PLAN-WDROZENIA.md` sekcja 12.

## A. Core / orkiestracja

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `job_scheduler.py` | Centralny scheduler WSZYSTKICH skryptów cyklicznych — jeden proces zamiast osobnego wpisu w Harmonogramie na każdy skrypt, `config/schedule.yaml` (interwał/enabled na zadanie), zmiana harmonogramu na żywo bez restartu (`--set-interval`/`--enable`/`--disable`), stan każdego zadania w `runs/scheduler_status.json` (`--status`) — na nim ma się opierać monitoring całości mechanizmu | JEDYNE zadanie w Harmonogramie zadań Windows, instalowane od razu przy starcie | infra |
| `runner_loop.py` | Główna pętla: pobiera zadania, kolejkuje, uruchamia workery, aktualizuje stan | Wg `config/schedule.yaml` przez `job_scheduler.py` (albo samodzielnie, `--loop`, starsze podejście) | infra |
| `task_router.py` | Klasyfikuje zadanie z Projectly na typ i wymagany worker (Power BI / CRM / Ads / pliki / mail / dev) | Po pobraniu zadania | infra |
| `state_store.py` | Trzyma stan zadania (SQLite/JSON) niezależnie od modelu AI — pozwala wznowić po restarcie | Każda zmiana stanu | infra |
| `heartbeat.py` | Zapisuje `heartbeat.json` co 30-60s | Cyklicznie w tle | infra |
| `watchdog.py` | Wykrywa brak heartbeat, restartuje runner lub eskaluje do Projectly | Cyklicznie, niezależny proces | infra |

## B. Projectly (komunikacja i zadania)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `projectly_poller.py` | Odpytuje API/MCP Projectly o nowe/przypisane zadania i komentarze-decyzje | Cyklicznie (np. co 30-60s) | infra |
| `projectly_reporter.py` | Dopisuje komentarz z podsumowaniem wg szablonu z planu wdrożenia | Po zakończeniu każdego zadania | zielone |
| `projectly_self_review.py` | LLM-judge: porównuje rezultat z `acceptance_criteria` zadania, ocenia pass/fail, dopisuje ocenę | Przed poproszeniem o akceptację | zielone |
| `projectly_status_sync.py` | Mapuje wewnętrzny status runnera na status zadania w Projectly | Przy każdej zmianie stanu | infra |
| `projectly_decision_parser.py` | Parsuje odpowiedź człowieka (komentarz/status) na `approve`/`reject`/`changes_requested` | Po wykryciu nowego komentarza na eskalowanym zadaniu | infra |
| `live_status_publisher.py` | Utrzymuje jeden, stały, nadpisywany wpis "status na żywo" per bot-rola w Projectly (zadanie w toku, kolejka, koszt, zdrowie) — nie kolejny komentarz, tylko zawsze aktualny stan (PLAN-WDROZENIA.md sekcja 2) | Harmonogram, co 1-2 min | zielone |

## C. Walidacja i auto-zatwierdzanie (priorytet — rozwiązuje problem z czasem admina)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `risk_classifier.py` | Klasyfikuje planowaną akcję jako zielona/żółta/czerwona wg `approval_policy.yaml` | Przed wykonaniem każdej akcji | infra |
| `approval_policy.yaml` + `policy_loader.py` | Deklaratywne reguły ryzyka i progów auto-akceptacji, edytowalne bez zmiany kodu | Wczytywane przy starcie runnera | infra |
| `validator_pool.py` | Uruchamia równolegle N niezależnych walidatorów dla żółtej akcji i zbiera głosy | Po wykonaniu żółtej akcji, przed zatwierdzeniem | infra |
| `validator_technical.py` | Walidator: testy techniczne/skrypt sprawdzający (kod wyjścia, dane kontrolne) | Wywoływany przez `validator_pool.py` | infra |
| `validator_visual.py` (`vision_reviewer.py`) | Walidator: ocena zrzutu ekranu przez model AI (czy wygląda poprawnie, brak błędów wizualnych) | Wywoływany przez `validator_pool.py` | infra |
| `validator_scope.py` | Walidator: czy akcja mieści się w zadeklarowanym zakresie zadania i limicie kosztu | Wywoływany przez `validator_pool.py` | infra |
| `auto_approve_yellow.py` | Jeśli głosy walidatorów ≥ próg z polityki — auto-zatwierdza, loguje kto/co zatwierdziło | Po zebraniu głosów z `validator_pool.py` | żółte |
| `escalate_to_human.py` | Dla czerwonych i spornych żółtych: tworzy w Projectly osobne zadanie przypisane człowiekowi (nie tylko komentarz) — z kontekstem, uzasadnieniem i linkami do screenshotów/diffów (patrz PLAN-WDROZENIA.md sekcja 4) | Gdy akcja czerwona lub walidatory bez zgody | infra |
| `human_response_validator.py` | Sprawdza, czy komentarz człowieka na eskalowanym zadaniu faktycznie rozstrzyga sprawę (jednoznaczna decyzja/wartość), czy trzeba dopytać | Po nowym komentarzu na zadaniu-eskalacji | infra |
| `continuation_task_creator.py` | Po pozytywnej weryfikacji odpowiedzi człowieka — tworzy w Projectly nowe zadanie-kontynuację dla agenta z decyzją człowieka wbudowaną w kontekst | Po `human_response_validator.py` (wynik: wystarczające) | infra |
| `bounded_red_executor.py` | Wykonuje czerwoną akcję bez pytania, jeśli mieści się w granicy liczbowej z `approval_policy.yaml` (bounded autonomy, PLAN-WDROZENIA.md sekcja 3); poza granicą przekazuje do `escalate_to_human.py` | Gdy `risk_classifier.py` oznaczy akcję jako czerwoną z dopasowaną granicą w polityce | czerwone w granicach |
| `validator_prompt.py` | Lokalny walidator wstrzyknięć promptów w treści zewnętrznej — heurystyka regex zawsze + opcjonalny lokalny model (Hermes/Ollama) jako druga opinia; wykrycie eskaluje niezależnie od koloru zadania | Przed klasyfikacją ryzyka, na każdym zadaniu | infra (blokuje do eskalacji) |

## D. Screenshoty i weryfikacja wizualna

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `screenshot_capture.py` | Uniwersalny zrzut (pełny ekran / okno / element), wspólny dla wszystkich workerów | Wywoływany przez workery Power BI/Ads/CRM | zielone |
| `screenshot_diff.py` | Porównanie ze zrzutem bazowym (perceptual diff), oznacza odchylenia | Po każdej zmianie wizualnej | zielone |
| `screenshot_annotate.py` | Nakłada opis/znaczniki błędów na zrzut do raportu końcowego | Przed dołączeniem do raportu | zielone |

## E. Power BI

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `pbip_validate.py` | Otwiera PBIP, uruchamia walidację schematów PBIR/TMDL, generuje raport (PBI-01) | Zadanie typu `powerbi_validation` | zielone |
| `pbip_screenshot_all_pages.py` | Przez Desktop Bridge robi zrzuty wszystkich stron raportu | Część `pbip_validate.py` | zielone |
| `pbip_edit_tmdl.py` | Kontrolowana edycja modelu/miar (TMDL) na osobnej gałęzi (PBI-02) | Zadanie typu `powerbi_fix` | żółte |
| `pbi_service_check.py` | REST API: status odświeżenia, dostęp, workspace | Zadanie cykliczne / na żądanie | zielone |

## F. CRM (przez MCP)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `zoho_crm_client.py` | Konektor do Zoho CRM przez MCP — rekordy, tagi, zapytania COQL. **Nie napisany jeszcze** — dziś tylko wpis w `config/integrations.yaml` | — | infra |
| `crm_sync_task.py` | Odczyt/zapis rekordów CRM powiązanych z zadaniem (np. status leada), korzysta z `zoho_crm_client.py` | Zadanie typu `crm_update` | żółte (odczyt: zielone) |
| `crm_report_generator.py` | Generuje podsumowania na podstawie zapytań CRM (np. COQL) do wykorzystania w innych zadaniach | Zadanie cykliczne / na żądanie | zielone |

## G. Meta Ads i TikTok Ads

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `meta_ads_api_client.py` | Odczyt kampanii i kontrolowane zmiany przez Marketing API w granicach limitu | Zadanie typu `ads_check` / `ads_adjust` | żółte (budżet: **czerwone**) |
| `meta_ads_ui_fallback.py` | Playwright dla funkcji niedostępnych w API — stan kampanii, zrzut, weryfikacja | Gdy API nie pokrywa potrzeby | żółte |
| `tiktok_ads_api_client.py` | Odczyt kampanii i kontrolowane zmiany przez TikTok Marketing API, ten sam wzorzec ryzyka co Meta Ads | Zadanie typu `ads_check` / `ads_adjust` | żółte (budżet: **czerwone**) |
| `ad_copy_generator.py` | Generuje wiele wariantów tekstu reklamowego dopasowanych do buyer person z `persony-sprzedaz/` (PLAN-WDROZENIA.md sekcja 20) | Na żądanie / przed cyklem testowym | zielone |
| `ad_set_launcher.py` | Uruchamia wariant jako mały test na Meta/TikTok w ramach budżetu testowego | Po `ad_copy_generator.py` | czerwone w granicach (`ad_test_launch`, bounded red) |
| `ad_performance_analyzer.py` | Liczy CTR/CPC/CPA per testowany wariant, klasyfikuje pause/scale/keep_testing — czysty Python bez AI | Harmonogram, co 48h | zielone |
| `ad_test_report.py` | Publikuje raport 48h w Projectly, tworzy zadania follow-up (pauza = żółte, skalowanie budżetu = czerwone) | Harmonogram, co 48h, po `ad_performance_analyzer.py` | zielone (raport) → dziedziczy ryzyko z konkretnej rekomendacji |

## H. E-mail i inny agent (przez MCP)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `mcp_email_agent_bridge.py` | Łączy się przez MCP z dedykowanym agentem mailowym, przekazuje kontekst i prosi o draft | Zadanie typu `email_draft` | żółte |
| `microsoft_graph_mail_client.py` | Konektor Microsoft Graph dla jednej wspólnej skrzynki (odczyt + wysyłka) — `config/integrations.yaml` wpis `microsoft_365`. **Nie napisany jeszcze** | — | infra |
| `email_draft_reviewer.py` | Walidator treści/odbiorcy/załączników przed przekazaniem do wysyłki | Przed wysyłką | infra (blokuje do czerwonej akceptacji) |

## I. Google Workspace i SharePoint

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `google_workspace_client.py` | Konektor do konta Google (Docs/Sheets/Drive, Search Console, Analytics) — `config/integrations.yaml` wpis `google_workspace`. **Nie napisany jeszcze**, dokładny zakres uprawnień do potwierdzenia | — | infra |
| `google_docs_writer.py` | Tworzy/aktualizuje pliki Google Docs/Sheets przez API, korzysta z `google_workspace_client.py` | Zadanie typu `google_file` | żółte |
| `sharepoint_sync.py` | Microsoft Graph: upload/aktualizacja plików i folderów, archiwizacja artefaktów | Po zakończeniu każdego zadania z artefaktami | zielone |
| `mailerlite_client.py` | Konektor MailerLite REST API — kampanie (pełny zapis: draft/harmonogram/wysyłka/statystyki), subskrybenci/grupy/pola (wjazd do już zbudowanych automatyzacji) | — | infra |
| `mailerlite_report_analyzer.py` | Cotygodniowy raport z wysłanych maili: statystyki (open rate/CTR), czytelność tekstu (heurystyka), ocena tonu/tytułu (model). Ocena wyglądu — **nie zaimplementowana**, wymaga Playwright (PLAN-WDROZENIA.md sekcja 21) | Harmonogram, co tydzień | zielone (analiza) |

## J. Skille i samodoskonalenie

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `skill_registry.py` | Rejestr dostępnych skilli/narzędzi z metadanymi (opis, ryzyko, kontrakt wejścia/wyjścia) | Wczytywany przez plannera przy starcie | infra |
| `skill_usage_logger.py` | Loguje użycie skilli/skryptów i skutek (sukces/porażka/czas/koszt) | Po każdym użyciu skilla | zielone |
| `skill_improver_bot.py` | Cyklicznie analizuje logi z `skill_usage_logger.py`, proponuje poprawki do skilli/promptów, tworzy PR z propozycją (nie wdraża sam) | Harmonogram, np. raz w tygodniu | żółte (PR), nie merge |

## K. Monitoring, koszty, bezpieczeństwo

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `cost_tracker.py` | Sumuje koszt AI per zadanie/dzień, alarm po przekroczeniu limitu | Po każdym wywołaniu modelu | infra |
| `secret_scanner.py` | Skanuje logi/artefakty pod kątem sekretów przed zapisem/synchronizacją | Przed `sharepoint_sync.py` / commitem | infra |
| `kill_switch.py` | Sprawdza globalny plik/flagę STOP przy starcie każdej pętli runnera; jeśli aktywna, bezpiecznie przerywa (jak PAUSE) i nie podejmuje nowych akcji (PLAN-WDROZENIA.md sekcja 17) | Na starcie każdej iteracji `runner_loop.py` | infra |
| `system_health_monitor.py` | Patrzy na realny stan maszyny (RAM, czy oczekiwane skrypty faktycznie działają w systemie — nie tylko czy piszą heartbeat), publikuje status, eskaluje przy problemie. Uzupełnia `heartbeat.py`/`watchdog.py` (te widzą tylko czy runner "daje znać", nie widzą samego systemu) | Wg `config/schedule.yaml` przez `job_scheduler.py` (domyślnie co 2 min), albo samodzielnie `--loop --interval 120` | zielone |
| `machine_status_reporter.py` | Cogodzinny, czysto informacyjny (bez eskalacji) raport statusu maszyny do Projectly: wersje narzędzi, historia ostatniego bootstrapu, RAM | Wg `config/schedule.yaml` przez `job_scheduler.py` (domyślnie co godzinę), albo samodzielnie `--loop --interval 3600` | zielone |

## L. Asystent zadań ludzkich (proactive assist — patrz PLAN-WDROZENIA.md sekcja 5)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `human_task_scanner.py` | Cyklicznie przegląda zadania przypisane ludziom (nie tylko agentowi) w Projectly i klasyfikuje, gdzie agent może pomóc | Harmonogram, np. co godzinę | zielone |
| `human_task_partial_executor.py` | Wykonuje automatyzowalną część zadania człowieka, dopisuje komentarz "zrobiłem X, zostaje Ci Y" | Gdy `human_task_scanner.py` znajdzie automatyzowalną część | żółte (jak natywne ryzyko wykonanej czynności) |
| `human_task_briefing.py` | Przygotowuje opracowanie/research/draft ułatwiające człowiekowi wykonanie w pełni ludzkiego zadania, dołącza jako komentarz/załącznik | Gdy zadanie wymaga researchu, ale decyzję/wykonanie musi podjąć człowiek | zielone |
| `task_feedback_requester.py` | Po zamknięciu zadania: komentarz z prośbą o feedback + osobne zadanie feedbackowe w Projectly + mail (przez `email_safety.yaml` dziś zawsze do Pawła/Aldony) | Zadanie zmienia status na "done" | zielone |

## M. Raporty, porządkowanie danych i podsumowania (priorytet #2 — patrz PLAN-WDROZENIA.md sekcja 10)

Wynika wprost z analizy realnych raportów godzin: pierwsza próbka (INDEKA/DIVERSE) pokazała ok. 175h firefightingu danych; pełny raport całego zespołu (czerwiec-sierpień 2026, 1997h) potwierdza to na większej skali — 214h w 114 wpisach, plus dodatkowo 298h czasu zalogowanego jako wciąż "otwarte" (patrz `PLAN-WDROZENIA.md` sekcja 10) — stąd `stale_time_entry_nudger.py` niżej.

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `source_schema_watcher.py` | Pilnuje struktury plików źródłowych (Excel/Google Sheets), wykrywa zmianę kolumny/arkusza/typu zanim odświeżenie się wywali, tworzy zadanie dla właściciela pliku | Cyklicznie / przed każdym zaplanowanym odświeżeniem | zielone |
| `stale_time_entry_nudger.py` | Skanuje wpisy czasu/zadania utknięte w statusie "otwarte"/"w toku" dłużej niż ustalony próg (np. 5 dni roboczych) i tworzy przypomnienie dla właściciela o domknięciu | Harmonogram (codziennie) | zielone |
| `data_contract_validator.py` | Waliduje plik źródłowy wobec uzgodnionego kontraktu struktury (per klient/proces) | Przed przepięciem/odświeżeniem raportu | zielone |
| `pq_error_triage` (skill) | Klasyfikuje wklejony błąd Power Query (zmieniona kolumna, typ danych, ścieżka, uprawnienia) i podaje gotową poprawkę | Na żądanie, po błędzie odświeżenia | zielone |
| `report_builder.py` | Buduje/aktualizuje raporty poza Power BI (Excel/Google Sheets/dokument) wg szablonu i zadeklarowanego rezultatu (Kadry, Finansowy, Dane ruchy mag) | Zadanie typu `report_build` | żółte |
| `data_tidy.py` | Porządkuje dane źródłowe na żądanie: deduplikacja, ujednolicenie formatów, uzupełnianie braków | Zadanie typu `data_tidy` lub jako krok przed `report_builder.py` | żółte |
| `newsletter_drafter.py` | Przygotowuje cykliczny draft newslettera z materiału źródłowego (zmiany produktowe, notatki, artykuły) | Harmonogram (np. tygodniowy) / zadanie typu `newsletter_draft` | zielone |
| `digest_generator.py` | Generuje cykliczny digest aktywności z Projectly (przed Daily/Weekly, do skrócenia lub częściowego zastąpienia spotkania) | Harmonogram, przed spotkaniem cyklicznym | zielone |
| `weekly_team_report.py` | Raport tygodniowy całego zespołu: zrobione/przeterminowane zadania (`digest_generator`) + zaległe wpisy czasu (`stale_time_entry_nudger`) + interpretacja słabych stron (model) | Harmonogram, raz w tygodniu | zielone |
| `content_summarizer.py` | Streszcza na żądanie długi materiał (maile, notatki ze spotkań, raporty) do krótkiej wersji | Zadanie typu `summarize` | zielone |
| `digest_audio.py` | TTS nad tekstem już wygenerowanym przez `digest_generator.py` — nie generuje treści od nowa, tylko narracja głosowa dla wybranych, ważniejszych podsumowań | Na żądanie / cykliczny digest tygodniowy | zielone |
| `digest_video.py` | Narracja TTS nad prezentacją/dashboardem, montaż — tylko dla dużych deliverabli (np. miesięczne podsumowanie dla klienta), nie domyślny format | Na żądanie | zielone |

## N. Intake — tworzenie i rozdzielanie zadań (mail i inne źródła, patrz PLAN-WDROZENIA.md sekcja 11)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `email_intake_triage.py` | Czyta skrzynkę (MCP/Graph), klasyfikuje treść (zlecenie/pytanie/błąd/zmiana), tworzy opisane zadanie w Projectly | Cyklicznie / webhook nowej wiadomości | zielone |
| `task_routing_classifier.py` | Dopasowuje nowe zadanie do właściciela wg słów kluczowych klienta/projektu i typu pracy; domyślnie do bota, jeśli w pełni automatyzowalne | Po utworzeniu zadania przez `email_intake_triage.py` | infra |
| `routing_confidence_check.py` | Sprawdza pewność klasyfikacji przed auto-przypisaniem; poniżej progu zadanie trafia do wspólnej puli z adnotacją do ręcznego przypisania | Po `task_routing_classifier.py` | infra |
| `other_source_intake.py` | Ten sam wzorzec intake dla innych kanałów (Teams, CRM, formularz) — adapter per źródło, wspólna klasyfikacja i routing | Cyklicznie / webhook per źródło | zielone |

## O. Retro-audyt i tryb rozmowy (patrz PLAN-WDROZENIA.md sekcje 14 i 16)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `task_retro_auditor.py` | Przechodzi przez zamknięte/nieudane zadania w Projectly za okres, robi ponowną ewidencję czasu/kosztu wg klienta/projektu, diagnozuje powtarzające się wzorce i proponuje automatyzacje do `SKRYPTY.md` (jako zadanie do przeglądu, nie cichy log) | Harmonogram, co miesiąc | żółte (rekomendacja do przeglądu) |
| `audit_query.py` | Odpytuje `state_store.py`/`events.jsonl`/historię Projectly w naturalnym języku — baza pod tryb rozmowy ("dlaczego zrobiłeś X zamiast Y", "co się działo w INDECE w tym tygodniu") | Na żądanie, w sesji rozmowy z agentem | zielone |
| `miro_read_client.py` | Konektor do Miro przez connector (tylko odczyt) — wyciąga kontekst/notatki z boardów jako dodatkowe źródło dla trybu rozmowy i Stratega. **Nie napisany jeszcze** | Na żądanie | zielone |

## P. Raporty biznesowe cykliczne (patrz PLAN-WDROZENIA.md sekcja 18)

Cotygodniowa analiza całej firmy — sprzedaż, wydatki reklamowe, finanse, widoczność w sieci — z gotowym planem wdrożenia, klasyfikowanym wg tego samego trójstopniowego ryzyka co reszta systemu.

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `zanfia_client.py` | Konektor do zanfia.com (platforma kursów) przez MCP — dane sprzedażowe kursów. **Nie napisany jeszcze** | — | infra |
| `sales_report_builder.py` | Cykliczny raport sprzedażowy z systemu transakcyjnego + `zanfia_client.py` | Harmonogram, co tydzień | zielone |
| `ad_spend_report_builder.py` | Cykliczny raport wydatków reklamowych (Meta Ads + inne kanały) | Harmonogram, co tydzień | zielone |
| `infakt_export.py` | Pobiera dane księgowe z inFakt (API jeśli dostępne, inaczej eksport CSV z portalu) przez dedykowane konto bota | Harmonogram, co tydzień / przed `company_financial_report_builder.py` | zielone (odczyt) |
| `company_financial_report_builder.py` | Łączy system transakcyjny + `infakt_export.py` w raport finansowy całej firmy | Harmonogram, co tydzień | zielone |
| `web_visibility_report_builder.py` | Raport widoczności w sieci: Google Search Console + Analytics oraz social media | Harmonogram, co tydzień | zielone |
| `weekly_business_review.py` | Agreguje cztery powyższe raporty, generuje wnioski i gotowy plan wdrożenia dla każdego, klasyfikuje wg ryzyka (zielone/żółte/czerwone/bounded red) i kieruje dalej zgodnie z resztą systemu | Harmonogram, co tydzień, po zakończeniu raportów cząstkowych | zielone (analiza) → dziedziczy ryzyko z konkretnego wdrożenia |

## Q. Bootstrap nowego komputera (patrz SKALOWANIE.md sekcja 4 — planować teraz, budować dopiero przy drugim komputerze)

| Skrypt | Cel | Wyzwalacz | Ryzyko |
|---|---|---|---|
| `bootstrap_install_git.ps1` | Instaluje gita (winget → fallback: pobranie z GitHuba, cicha instalacja) — świeża maszyna/Windows Server go nie ma | Ręcznie, pierwszy krok na zupełnie świeżej maszynie | infra |
| `bootstrap_install_python.ps1` | Instaluje Python 3.11+ (winget → fallback: instalator z python.org, cicha instalacja udokumentowanymi przełącznikami) | Ręcznie, po gicie | infra |
| `bootstrap_install_claude_code.ps1` | Instaluje Claude Code (CLI) natywnym instalatorem — narzędzie terminalowe do dalszej pracy nad kodem | Ręcznie, po gicie | infra |
| `bootstrap_install_claude_desktop.ps1` | Pobiera i uruchamia instalator Claude Desktop (opcjonalnie, interfejs okienkowy z sesjami w chmurze) | Ręcznie, opcjonalne | infra |
| `bootstrap_all.ps1` | Orkiestrator — uruchamia git/Python/Claude Code/klon repo/sekrety/test dymny jednym poleceniem, pokazuje status i czas trwania każdego kroku, zapisuje historię | Ręcznie, zamiast ręcznego odpalania poniższych po kolei | infra |
| `bootstrap_install.ps1` | Przygotowuje system (sprawdza RAM, wyłącza uśpienie, tworzy dedykowane konto), instaluje zależności, klonuje rdzeń | Ręcznie, raz przy dołączaniu nowego komputera | infra |
| `bootstrap_init_secrets.py` | Tworzy scentralizowany folder `secrets/` (`.env` + szablony MCP na podstawie `integrations.yaml`) — jedno miejsce do ręcznego wypełnienia dostępów | Po `bootstrap_install.ps1`, przed pierwszym uruchomieniem | infra |
| `bootstrap_register.py` | Odczytuje przypisaną rolę, rejestruje komputer w `role_registry.py` i w Projectly | Po `bootstrap_init_secrets.py` | infra |
| `bootstrap_smoke_test.py` | Przepuszcza jedno testowe zadanie przez pełen cykl queued→done, sprawdza heartbeat i reakcję `kill_switch.py`, zanim komputer trafi do produkcji | Ostatni krok bootstrapu, przed przekazaniem komputera do pracy | zielone |
