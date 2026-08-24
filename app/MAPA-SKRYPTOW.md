# Mapa skryptów — co do czego, kiedy wywołać

Ten plik ma jeden cel: **żebym (agent pracujący w tym repo) nie musiał za każdym razem
przeszukiwać 90 plików, żeby znaleźć właściwy skrypt.** `app/README.md` opisuje HISTORIĘ
i STAN (co działa/nie działa, kiedy przetestowane) — ten plik opisuje FUNKCJĘ: do czego
service, jak go wywołać, z czym jest powiązany. Czytaj to PRZED grepowaniem repo od zera.

Zasada: jeśli nie wiesz, którego skryptu użyć — najpierw sprawdź tabelę "Chcę zrobić X"
niżej, potem sekcję kategorii. Jeśli i tam nie ma odpowiedzi, dopiero wtedy przeszukuj kod.

## Chcę zrobić X → wywołaj Y

| Chcę... | Skrypt / polecenie |
|---|---|
| Uruchomić jeden przebieg pętli agenta na mocku | `python runner_loop.py` |
| Uruchomić pętlę agenta w trybie ciągłym | `python runner_loop.py --loop` |
| Sprawdzić stan WSZYSTKICH zadań cyklicznych naraz | `python job_scheduler.py --status` |
| Odpalić jedno zadanie cykliczne na żądanie (bez czekania na harmonogram) | `job_scheduler.run_job_by_name(nazwa)` albo przez `dashboard.py` |
| Podejrzeć historię przebiegów / edytować harmonogram bez YAML-a | `python dashboard.py` → `http://127.0.0.1:8787/` |
| Zatrzymać/wstrzymać agenta z panelu (nie awaryjnie) | `control.py` (stany running/paused/stopped) |
| Zatrzymać WSZYSTKO natychmiast, awaryjnie | `kill_switch.py` (plik-flaga, ostatnia linia obrony) |
| Ręcznie założyć zadanie testowe w REALNYM Projectly | `python projectly_seed_task.py` |
| Sprawdzić czy token Projectly/MCP działa i co widać | `python -c "..."` przez `projectly_client.get_client()` (patrz sesja diagnostyczna 24.08.2026) albo `projectly_client_smoke_test.py` (bez sieci) |
| Sprawdzić jakich zmiennych z `secrets/.env` brakuje | `python secrets_audit.py` |
| Utworzyć `secrets/.env` + szkielety MCP na nowej maszynie | `python bootstrap_init_secrets.py` |
| Zarejestrować rolę maszyny (dev/marketing/...) | `python bootstrap_register.py <rola>` |
| Uruchomić PEŁNY test dymny repo (bramka jakości commitu) | `python self_check.py` |
| Zaktualizować kod na maszynie z GitHub (git pull) | `repo_updater.py` (job w schedulerze: `repo_update`) |
| Sprawdzić czy sekrety Microsoft Graph (mail) w ogóle łapią token | `python graph_verify.py` (NIE wysyła maila) |
| Sprawdzić czy dostęp do SharePoint działa | `python sharepoint_verify.py` |
| Wysłać / zaszkicować maila | `email_client.py` (NIGDY bezpośrednio `microsoft_graph_mail_client.py` — brak przekierowania bezpieczeństwa) |
| Zapisać wygenerowany plik na SharePoint | `sharepoint_client.py` |
| Wygenerować raport tabelaryczny (md/csv/xlsx) | `report_builder.py` |
| Wygenerować dokument narracyjny (pdf/docx/qmd) | `document_builder.py` |
| Zbudować/odświeżyć kontekst projektu do promptu | `kontekst_projektow_seed.py` (generuje szkic z danych Projectly) |
| Sprawdzić zdrowie maszyny (RAM, czy runner żyje) ręcznie | `python system_health_monitor.py` |
| Sprawdzić zużycie/koszt Claude i ile zadań jeszcze | `usage_monitor.py` / `cost_tracker.py` |
| Wyeksportować historię decyzji agenta do analizy offline | `python export_decisions.py` |
| Dodać zadanie z lokalnego notatnika (obok Projectly) | dopisz linię do `inbox/zadania.txt`, przetworzy `notebook_intake.py` (job w schedulerze) |
| Zweryfikować strukturę projektu PBIP | `python pbip_validate.py <ścieżka>` |
| Zrobić zrzut konkretnego okna | `screenshot_capture.py` |
| Kliknąć/wpisać coś w aplikacji desktopowej (nie w przeglądarce) | `ui_actions.py` (przez `ui_lock.py` — serializacja) |
| Kliknąć/wypełnić formularz NA STRONIE (JS-rendered) | `browser_worker.py` (Playwright) |
| Tylko pobrać treść strony (GET, bez klikania) | `web_fetch_worker.py` |
| Odpowiedzieć na pytanie na podstawie pobranej treści strony | `web_answer.py` |
| Naprawić zły link źródłowy w zadaniu | `web_source_fixer.py` |
| Sprawdzić czy tekst zewnętrzny nie zawiera prompt injection | `validator_prompt.py` (dzieje się automatycznie PRZED klasyfikacją w `runner_loop.py`) |
| Poprosić o feedback po zamkniętym zadaniu | `task_feedback_requester.py` |
| Eskalować zadanie do człowieka | `escalation.escalate_to_human()` (przez `runner_loop.py`, nie ręcznie) |
| Wygenerować warianty tekstu reklamowego | `ad_copy_generator.py` |
| Policzyć CTR/CPC/CPA testu reklam | `ad_performance_analyzer.py` |
| Zrobić cotygodniowy raport z MailerLite | `mailerlite_report_analyzer.py` |
| Zrobić raport tygodniowy całego zespołu | `weekly_team_report.py` |
| Zrobić krótki digest przed daily/weekly | `digest_generator.py` |

## 1. Rdzeń pętli agenta

| Skrypt | Co robi |
|---|---|
| `runner_loop.py` | Główna pętla: pobiera zadania z Projectly → klasyfikuje ryzyko → routing do właściciela → walidacja (żółte) / granica bounded red (czerwone) → eskalacja sporne/czerwone → publikuje status. `--loop` dla trybu ciągłego. |
| `executor.py` | Realne wykonanie zadania wg typu (dziś: PBIP, screenshot, browser_task, fetch_url, integracje MailerLite/Zanfia). Ścieżki ograniczone do `ALLOWED_ROOTS` — fail-closed poza workspace. |
| `task_router.py` | Przypisanie zadania do właściciela po słowach kluczowych z `config/clients_routing.yaml`. Niska pewność → `unassigned_pool`. |
| `risk_classifier.py` | Kolor ryzyka (zielone/żółte/czerwone/bounded_red) wg `config/approval_policy.yaml`. |
| `risk_hint.py` | Poprawia kolor ryzyka NA PODSTAWIE TREŚCI zadania — Projectly dziś zawsze zwraca `yellow` na sztywno, to jest korekta. |
| `bounded_red_executor.py` | Pozwala wykonać czerwoną akcję BEZ pytania, ale TYLKO gdy mieści się w jawnej granicy liczbowej w `approval_policy.yaml → bounded_red` (dziś pusta lista — świadomie). |
| `task_thinker.py` | Bot "myśli" nad zadaniem realnym modelem zanim/zamiast klasyfikacji — pierwszy krok od zaślepki do realnej pracy. |
| `task_brief_builder.py` | Buduje brief kontekstowy z TRWAŁEJ historii (`state_store.events`), żeby decydent zawsze miał kontekst niezależnie od restartu. |
| `state_store.py` | Stan zadań + historia zdarzeń (`events`) w SQLite (`runs/state.db`) — przeżywa restart. `log_decision()`, `get_recent_decisions()`. |
| `cost_tracker.py` | Sumuje koszt AI per zadanie/dzień, wyzwala kill switch po przekroczeniu dziennego limitu. |
| `cost_estimator.py` | Szacunek kosztu POJEDYNCZEGO wywołania modelu (naprawia dziurę: Claude Code dawał 0.0, kill switch nie widział kosztu). |
| `kill_switch.py` | Globalny plik-flaga STOP, sprawdzany na starcie pętli i przez workery. Ostatnia linia obrony, nie zamiennik walidacji. |
| `control.py` | Sterowanie agentem z panelu operatora: running / paused / stopped (mniej brutalne niż kill switch). |
| `heartbeat.py` / `watchdog.py` | `heartbeat.py` zapisuje `runs/heartbeat.json` co cykl; `watchdog.py` wykrywa jego nieaktualność → `ALERT.flag`. |
| `poprawka_materialu.py` | Pętla poprawek wg zastrzeżeń bramki jakości — bez tego każda drobna wada kończyła zadanie eskalacją. |
| `tool_registry.py` | "Czy TO narzędzie z TYMI parametrami wolno uruchomić" — kontrakty z `config/tool_contracts.yaml`. Model nie dostaje dowolnego shella. |
| `skill_registry.py` / `skill_usage_logger.py` | Rejestr skilli z wersją/ryzykiem (`config/skills_manifest.yaml`) + log użycia (sukces/porażka/koszt/czas). |
| `model_registry.py` | Jedno miejsce: jakiego modelu użyć i ile kosztuje (`config/models.yaml` czy podobne — wzorzec jak `tool_registry`). |

## 2. Bramka jakości (walidacja PRZED człowiekiem)

| Skrypt | Co robi |
|---|---|
| `bot_gustaw_bramka.py` | Orkiestrator — przepuszcza zadanie po kolei przez pozostałych botów walidujących, wg `config/validation_gate.yaml` (kolejność, obowiązkowość, próg zgód). |
| `bot_bartek_dubler.py` | Powtarza to samo zadanie niezależnie i porównuje wynik — łapie regresję/niedeterminizm. |
| `bot_franek_funkcjonalny.py` | Testy funkcjonalne na REALNYM efekcie (plik/JSON/PBIP/liczby). |
| `bot_oskar_wizja.py` | Ocena wizualna zrzutu ekranu modelem (Anthropic główny recenzent, Ollama druga opinia). |
| `bot_common.py` | Wspólny kontrakt sygnatury dla wszystkich botów walidujących. |
| `validators.py` / `validator_pool.py` | 3 walidatory równolegle dla żółtych akcji (technical/scope/visual), próg zgody z polityki. |
| `validator_prompt.py` | Wykrywa próbę wstrzyknięcia instrukcji w treści zewnętrznej — sprawdzane PRZED klasyfikacją, wykrycie zawsze eskaluje. |

## 3. Komunikacja z człowiekiem / eskalacja / feedback

| Skrypt | Co robi |
|---|---|
| `escalation.py` | `escalate_to_human` (nowe zadanie dla człowieka, nie tylko komentarz) → `human_response_validator` (jednoznaczność odpowiedzi) → `continuation_task_creator`. Widoczny ciąg oryginał→eskalacja→kontynuacja przez `zbot_link_tasks`. |
| `task_feedback_requester.py` | Po zamknięciu zadania: komentarz z pytaniem o feedback + osobne zadanie feedbackowe + mail. Idempotentne (`runs/feedback_requested.json`). |

## 4. Integracja z Projectly (MCP)

| Skrypt | Co robi |
|---|---|
| `projectly_client.py` | Główny klient. Dwie implementacje: `ProjectlyClient` (realny, przez MCP) i `MockProjectlyClient` (pliki JSON w `runs/`). Metody: `get_new_tasks`, `post_comment`, `get_comments`, `update_status`, `create_task`, `get_task_relations`, `publish_status`, `get_week_report`, `create_knowledge`, `update_knowledge`. **Nazwy narzędzi MCP realnie wołane (od 24.08.2026) — patrz `config/projectly.yaml → mcp_tool_usage`, dużo z nich ma prefiks `zbot_`.** |
| `mcp_client.py` | Sama "hydraulika" transportu MCP-over-HTTP (JSON-RPC, Streamable HTTP: initialize → tools/call). Nie wie nic o zadaniach. |
| `projectly_seed_task.py` | Ręczne zakładanie zadania w REALNYM Projectly z CLI — druga strona pętli, do kontrolowanych testów na żywym koncie. |
| `kontekst_projektow_seed.py` | Generuje szkice kontekstu projektu (kto po drugiej stronie, jakie systemy) z danych już w Projectly, zapisuje do `kontekst/projekty/`. |
| `kontekst_firmy.py` | Osadza agenta w realiach firmy — wczytuje `kontekst/*` i dokleja do promptu. |
| `config/projectly.yaml` | Config: mapowanie rola→konto AI (`role_to_account`), zakres pollowania, `mcp_tool_usage` (mapa funkcja→narzędzie MCP), `live_status.transport`. |

**Diagnostyka MCP na żywo** (gdy coś nie działa albo trzeba sprawdzić nowe narzędzia produkcji):
```python
import env_bootstrap
from projectly_client import get_client
client = get_client()          # realny klient, jeśli PROJECTLY_API_KEY w env
mcp = client._mcp
mcp._ensure_initialized()
result = mcp._rpc('tools/list', {})   # pełna lista narzędzi na produkcji
```
Tak sprawdziłem 24.08.2026, że produkcja dodała rodzinę `zbot_*` (patrz commit z tego dnia).

## 5. Status na żywo / monitorowanie floty

| Skrypt | Co robi | Częstotliwość |
|---|---|---|
| `live_status_publisher.py` | Status bota (kolejka, koszt, zdrowie, bieżące zadanie) → `ProjectlyClient.publish_status("dev"/rola, ...)`. | co 1-2 min |
| `machine_status_reporter.py` | Wersje narzędzi (git/python/claude), ostatni bootstrap, RAM → `publish_status("machine-status", ...)`. | co godzinę |
| `system_health_monitor.py` | RAM + czy oczekiwane skrypty faktycznie działają → `publish_status("system-health", ...)`, eskaluje zadanie przy `critical`. | co ~2 min |
| `kacper_monitor.py` | Czyta wspólny dziennik (`state_store.events` + `job_scheduler` historię), wykrywa POWTARZALNE awarie (job albo skill) → JEDNO zadanie naprawcze/dzień (dedup) → `publish_status("kacper-monitor", ...)`. Domyślnie WYŁĄCZONY w schedulerze. | na żądanie / job |
| `knowledge_digest_publisher.py` | Cogodzinny digest "ostatnia aktywność" per konto AI → baza wiedzy Projectly (`zbot_create_knowledge`/`zbot_update_knowledge`, upsert po id z `runs/knowledge_entry_ids.json`). | co godzinę |
| `job_scheduler.py` | Centralny scheduler WSZYSTKICH cyklicznych skryptów — `config/schedule.yaml`. `--status`, `run_job_by_name()`, historia w `runs/run_history.jsonl` (pełne stdout+stderr+return). |
| `scheduler_lock.py` | Blokada: tylko jedna żywa instancja `job_scheduler.py` naraz. |
| `dashboard.py` (+ `dashboard.html`) | Panel w przeglądarce `http://127.0.0.1:8787/` — historia przebiegów, edycja harmonogramu na żywo, "uruchom teraz", szczegół przebiegu. Tylko localhost. |
| `usage_monitor.py` | Zużycie Claude + "ile zadań jeszcze" — widoczne w statuslinii terminala. |

**Uwaga:** publikacja statusu do zakładki mastera w Projectly (`/dashboard/agent-monitoring`) idzie przez `zbot_post_agent_status` — to JEDYNE miejsce, które o tym decyduje, jest w `projectly_client.py::_publish_status_via_tool`. Zob. `PLAN-MONITOROWANIE-AGENTOW-*.md` dla pełnego kontraktu danych.

## 6. Raporty i digesty (dla ludzi)

| Skrypt | Co robi |
|---|---|
| `digest_generator.py` | Krótki digest z Projectly (zrobione/przeterminowane/w toku) PRZED daily/weekly. |
| `weekly_team_report.py` | Raport tygodniowy całego zespołu: zrobione/przeterminowane + zaległe wpisy czasu + opcjonalna interpretacja modelem. |
| `ad_test_report.py` | Cykliczny raport testu reklam co 48h (osobny, częstszy cykl niż weekly). |
| `mailerlite_report_analyzer.py` | Cotygodniowy raport z maili MailerLite — czytelność, ton, tytuł (model). |
| `report_builder.py` | Generyczny silnik TABEL (markdown/CSV/XLSX) z listy rekordów. |
| `document_builder.py` | Dokumenty NARRACYJNE (PDF/DOCX/QMD) — nagłówek + tekst/tabela w sekcjach. Rozszerza `report_builder.py`. |
| `export_decisions.py` | Zrzut historii decyzji agenta z `runs/state.db` do CSV/JSONL, do analizy offline. Nic nie kasuje. |

## 7. Marketing / reklamy / sprzedaż

| Skrypt | Co robi |
|---|---|
| `ad_copy_generator.py` | Warianty tekstu reklamowego (nagłówek/treść/CTA) z kontekstem buyer person. |
| `ad_performance_analyzer.py` | CTR/CPC/CPA po 48h, klasyfikacja (pause/scale/keep_testing) — czysty Python, bez AI. |
| `ad_set_launcher.py` | Uruchamia test reklamowy w granicy bounded_red — STUB, prawdziwe wywołanie Meta/TikTok API jeszcze nie napisane. |
| `meta_ads_client.py` | Konektor Meta Ads — READ-ONLY (kampanie, wydatki). Zmiana budżetu = red/bounded_red, celowo osobno. |
| `mailerlite_client.py` | Klient REST MailerLite. Fail-closed: brak klucza = wyjątek, nigdy ciche dane z mocka. |
| `integracje_worker.py` | Workery wołane z `executor.py`: zestawienie wysyłek MailerLite, podsumowanie sprzedaży Zanfia. |
| `zanfia_client.py` | MCP do zanfia.com (platforma kursów) — read-only wymuszone w kodzie. Stan: serwer odrzuca autoryzację (401). |
| `period_resolver.py` | "ostatni tydzień"/"wczoraj" → konkretne daty. Czysty Python, zero AI (celowo — model gubi dni). |

## 8. Poczta / dokumenty / Microsoft 365

| Skrypt | Co robi |
|---|---|
| `email_client.py` | Właściwy punkt wejścia do wysyłki maila. **KAŻDA wysyłka przekierowana do `config/email_safety.yaml`** (dziś Paweł/Aldona) — fail-closed, pusta lista blokuje. Nigdy nie wołaj `microsoft_graph_mail_client.py` bezpośrednio. |
| `email_draft_generator.py` | Draft z gotowego szablonu (`templates/email/*.md`). |
| `microsoft_graph_mail_client.py` | Realny klient Graph (app-only, `msal`) — WEWNĘTRZNY, owinięty przez `email_client.py`. |
| `graph_verify.py` | Czy sekrety `MS_GRAPH_*` łapią token i Graph wpuszcza. NIE wysyła maila. Diagnostyka przed wysyłką. |
| `sharepoint_client.py` | Zapis wygenerowanych dokumentów na SharePoint (`config/sharepoint.yaml`), jeden folder per zadanie. |
| `sharepoint_verify.py` | Czy token + dostęp do witryny/drive'a działa. NIE tworzy folderu — sam test. |
| `google_workspace_client.py` | Konektor Google Workspace przez konto serwisowe (JSON key), bez klikania "zezwól" — wzorzec serwerowy. |

## 9. Jakość danych źródłowych

| Skrypt | Co robi |
|---|---|
| `source_schema_watcher.py` | Wykrywa zmianę struktury pliku źródłowego (CSV) ZANIM odświeżenie się wywali, tworzy zadanie dla właściciela. |
| `data_contract_validator.py` | Waliduje plik wobec uzgodnionego kontraktu (`config/data_contracts/*.yaml`). |
| `stale_time_entry_nudger.py` | Znajduje wpisy czasu "otwarte" dłużej niż próg dni, grupuje wg osoby. |

## 10. Agent lokalny — wizja / UI / okna / przeglądarka

| Skrypt | Co robi |
|---|---|
| `screenshot_capture.py` | Zrzut całego ekranu / obszaru / KONKRETNEGO okna (PrintWindow/DWM, odporny na RDP). Karmi bota wizyjnego Oskara. |
| `window_manager.py` | Listowanie/fokus/granice okien + HWND — podstawa pracy na wielu okienkach. |
| `multi_window.py` | Praca na ~16 oknach: siatka, rozłożenie, RÓWNOLEGŁE zrzuty wszystkich. |
| `ui_actions.py` | Klik/wpisywanie/odczyt kontrolek przez UI Automation (pywinauto `uia`) — dla aplikacji desktopowych (Power BI, VS Code). |
| `ui_lock.py` | Serializacja sterowania ekranem: "jedno aktywne okno na zadanie". |
| `ocr_extract.py` | Twardy ODCZYT tekstu/liczb ze zrzutu (Tesseract → model wizyjny) — osobno od oceny "czy wygląda dobrze". |
| `file_search.py` | Szybkie przeszukiwanie plików dla skryptów deterministycznych (ripgrep → czysty Python fallback). |
| `browser_worker.py` | Zadania webowe wymagające KLIKANIA (Playwright) — nawigacja JS, formularze, zrzut po interakcji. Allowlista hostów w `tool_contracts.yaml`. |
| `pbi_desktop_bridge.py` | Otwiera PBIP w Power BI Desktop, zrzut okna raportu — karmi Oskara. Wymaga prawdziwego Windows z Power BI Desktop. |
| `pbip_validate.py` | Waliduje strukturę PBIP (JSON/TMDL) BEZ Power BI Desktop. |
| `web_fetch_worker.py` | Pobieranie treści (read-only GET) — TYLKO HTTPS, TYLKO hosty z allowlisty. |
| `web_answer.py` | Odpowiedź na pytanie z zadania na podstawie pobranej treści. |
| `web_source_fixer.py` | Samodzielna korekta adresu źródła, gdy wskazany link nie zawiera odpowiedzi. |

## 11. Bootstrap / instalacja maszyny

| Skrypt | Co robi |
|---|---|
| `bootstrap_init_secrets.py` | Tworzy `secrets/.env` + szkielety `secrets/mcp/*.json` z `config/integrations.yaml`. Jedno miejsce na wszystkie dostępy, idempotentne. |
| `bootstrap_register.py` | Krok 3 bootstrapu: zapisuje rolę lokalnie, ogłasza się w Projectly pierwszym statusem. Ręcznie, raz, przy nowym komputerze. |
| `env_bootstrap.py` | Centralny loader `.env`/`secrets/.env` (+ per-rola `secrets/agents/<rola>/.env`) — importowany przez KAŻDY moduł czytający klucz API. Wymusza też UTF-8 na stdout/stderr (bez tego konsola Windows pada na emoji). |
| `repo_updater.py` | `git pull --ff-only` jako funkcja — wpięta w scheduler (job `repo_update`). |
| `*.ps1` / `*.sh` w `instalacja/` | Przygotowanie systemu (Windows/Linux), klon repo, instalacja Git/Python/Claude Code — patrz `instalacja/` i `app/README.md` sekcja instalacji. Nie są `.py`, nie są tu wypisane osobno. |

## 12. Bezpieczeństwo / audyt / narzędzia deweloperskie

| Skrypt | Co robi |
|---|---|
| `secret_scanner.py` | Maskuje sekrety (password/token/api_key/...) w tekście/logach przed zapisem/synchronizacją. |
| `secrets_audit.py` | Pokazuje: czego kod SZUKA w env, co jest wypełnione, czego brak, który skrypt czego używa. NIGDY nie wypisuje wartości. |
| `self_check.py` | Samo-weryfikacja: uruchamia WSZYSTKIE `*_smoke_test.py`, drukuje ✅/❌. Uruchom po KAŻDEJ zmianie kodu przed commitem. |
| `notebook_intake.py` | Dodatkowa lokalna ścieżka zadań (`inbox/zadania.txt`) obok Projectly — ten sam pipeline, klient mock. Dedup po treści linii. |

## Powiązane pliki configu (szybki skorowidz)

| Config | Do czego |
|---|---|
| `config/approval_policy.yaml` | Progi zgody, `bounded_red` (dziś pusta lista celowo) |
| `config/clients_routing.yaml` | Słowa kluczowe → właściciel zadania |
| `config/validation_gate.yaml` | Kolejność/obowiązkowość botów bramki, próg zgód |
| `config/tool_contracts.yaml` | Co wolno uruchomić i z jakimi parametrami (`tool_registry.py`) |
| `config/skills_manifest.yaml` | Rejestr skilli, status (działa/planned) |
| `config/integrations.yaml` | Rejestr WSZYSTKICH kont/połączeń (bez kluczy — te w `secrets/`) |
| `config/projectly.yaml` | Konta AI, mapowanie MCP, transport statusu na żywo |
| `config/schedule.yaml` (z `schedule.default.yaml`) | Harmonogram wszystkich cyklicznych skryptów |
| `config/email_safety.yaml` | Kto realnie dostaje maile (przekierowanie bezpieczeństwa) |
| `config/sharepoint.yaml` / `sharepoint_sites.yaml` | Docelowa witryna/biblioteka SharePoint |
| `config/data_contracts/*.yaml` | Oczekiwana struktura plików źródłowych per klient/proces |
| `config/health_thresholds.yaml` | Progi `system_health_monitor.py` (RAM, oczekiwane skrypty) |
| `config/kacper_thresholds.yaml` | Progi `kacper_monitor.py` (ile awarii = zadanie naprawcze) |

## Jak aktualizować ten plik

Gdy dodajesz nowy skrypt albo zmieniasz przeznaczenie istniejącego — dopisz/zaktualizuj
wpis TUTAJ, w tym samym commicie co zmiana kodu. To jest żywy indeks, nie migawka
historyczna — jeśli się rozjedzie z kodem, przestaje działać jego jedyny cel.
