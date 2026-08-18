# Szkielet Fazy 0-2 — działający, przetestowany kod

To nie jest pseudokod ani dokumentacja — to realny, uruchomiony i przetestowany szkielet: fundament (Faza 0), pętla end-to-end (Faza 1), silnik walidacji i obieg eskalacji (Fazy 2-2b), plus struktura walidacji PBIP (Faza 3, bez zrzutów ekranu — patrz niżej) i bootstrap nowego komputera (`SKALOWANIE.md`).

## Co realnie działa i jest przetestowane

| Moduł | Co robi | Test |
|---|---|---|
| `state_store.py` | Stan zadań + historia zdarzeń w SQLite, przeżywa restart | ✅ |
| `heartbeat.py` / `watchdog.py` | Zapis i wykrywanie nieaktualnego heartbeatu | ✅ |
| `kill_switch.py` | Globalny STOP.flag, blokuje runner bez podejmowania akcji | ✅ |
| `risk_classifier.py` | Klasyfikacja zielone/żółte/czerwone z `approval_policy.yaml`, fail-closed dla nieznanych akcji | ✅ |
| `task_router.py` | Routing po słowach kluczowych z `clients_routing.yaml`, niska pewność → `unassigned_pool` | ✅ |
| `validators.py` + `validator_pool.py` | 3 walidatory równolegle (technical/scope/visual), próg zgody z polityki | ✅ |
| `validators.py::_call_vision_model` | Realne wywołanie modelu wizyjnego (pakiet `anthropic`) przy podanym zrzucie i kluczu | ⚠️ napisane i gałęzie bez klucza przetestowane; sama rozmowa z modelem nietestowana — brak klucza w tej sesji |
| **Bramka jakości (5 botów)** `bot_gustaw_bramka.py` + `bot_bartek_dubler.py` / `bot_franek_funkcjonalny.py` / `bot_oskar_wizja.py` / `bot_bozena_biznes.py` | Seria testów, przez którą przechodzi każde zadanie z efektem (żółte i zielone z efektem) ZANIM trafi do człowieka. **Gustaw** orkiestruje: **Bartek** powtarza zadanie i porównuje (regresja/niedeterminizm), **Franek** odpala testy funkcjonalne (plik/JSON/PBIP/liczby), **Oskar** ocenia zrzut ekranu modelem wizyjnym (Ollama→Anthropic), **Bożena** robi odbiór biznesowy wg persony + `config/business_context.yaml` + kryteriów akceptacji. Konfiguracja: `config/validation_gate.yaml` (kolejność, obowiązkowi, próg zgód). Bożena obowiązkowa → bez modelu bramka eskaluje (fail-closed) | ✅ logika bramki (wszystkie werdykty, scope guard, obowiązkowość) pokryta `validation_gate_smoke_test.py`; ocena modelu (Oskar/Bożena) realna, degraduje bez modelu |
| `escalation.py` | Tworzy zadanie dla człowieka (nie tylko komentarz), sprawdza jednoznaczność odpowiedzi, tworzy kontynuację | ✅ |
| `microsoft_graph_mail_client.py` + `email_client.py` | Realna wysyłka/szkice maila przez Microsoft Graph (app-only: `msal` token + REST). `EmailClient` przekierowuje KAŻDĄ wysyłkę do ludzi z `email_safety.yaml` (fail-closed). Realny klient włącza się tylko z pełnymi sekretami MS_GRAPH_* + `msal` + flagą `GRAPH_SEND_IMPLEMENTED`; inaczej mock, bez crasha | ✅ format wiadomości, obsługa kodów Graph, przekierowanie odbiorców, wybór realny/mock pokryte `graph_mail_smoke_test.py` (bez sieci); realna wysyłka do zweryfikowania z prawdziwą aplikacją Azure AD |
| `bounded_red_executor.py` | Sprawdza granicę liczbową bounded red — bez wpisu w polityce zawsze odmawia (bezpieczny domyślny stan) | ✅ |
| `cost_tracker.py` | Sumuje koszt dzienny, wyzwala kill switch po przekroczeniu limitu | ✅ |
| `secret_scanner.py` | Maskuje sekrety wg wzorca pola i kształtu klucza | ✅ |
| `live_status_publisher.py` | Buduje i publikuje status na żywo (kolejka, koszt, zdrowie) | ✅ |
| `skill_registry.py` / `skill_usage_logger.py` | Rejestr skilli z wersją, log użycia | ✅ |
| `pbip_validate.py` | Waliduje strukturę PBIP (JSON, TMDL) bez Power BI Desktop | ✅ (na syntetycznym przykładzie w `mock_data/sample_pbip/`) |
| `validator_prompt.py` | Wykrywa próby wstrzyknięcia instrukcji w treści zewnętrznej (heurystyka regex + opcjonalnie lokalny model przez Ollamę) — sprawdzane PRZED klasyfikacją, wykrycie zawsze eskaluje | ✅ heurystyka; opcjonalny lokalny model gracefully pomijany, gdy niedostępny |
| `runner_loop.py` | Spina wszystko: klasyfikacja → routing → walidacja/eskalacja → status → koszt | ✅ (`python runner_loop.py`) |
| `bootstrap_register.py` / `bootstrap_smoke_test.py` | Rejestracja roli i test dymny nowego komputera | ✅ |
| `bootstrap_install.ps1` | Przygotowanie systemu Windows i klon repo | ⚠️ **przetestowany realnie pod PowerShell Core (pwsh) w tej sesji** (z `-SkipSystemChecks`) — złapało i naprawiło 2 realne błędy (zła ścieżka w sprawdzeniu idempotencji, błędy `git`/`pip` nie zatrzymywały skryptu). Nieprzetestowane: fragmenty Windows-only (`Get-CimInstance`, `powercfg`, sprawdzenie roli administratora) — brak prawdziwego Windows w tej sesji |
| `bootstrap_install_vps.sh` | Odpowiednik dla Linuksa/VPS (`WDROZENIE-VPS-TESTOWE.md`) | ✅ **przetestowany end-to-end w tej sesji** — klon, venv, zależności, smoke test, wszystko przeszło |
| `bootstrap_install_git.ps1` | Instaluje samego gita (winget → fallback: pobranie instalatora z GitHuba i cicha instalacja) — dla świeżej maszyny/Windows Server, która go nie ma | ⚠️ logika wykrywania gita przetestowana pod PowerShell Core; zapytanie do API GitHuba i sama instalacja .exe nietestowane (ograniczenia sieci tej sesji / brak prawdziwego Windows) |
| `ad_copy_generator.py` | Generuje warianty tekstu reklamowego z realnym kontekstem buyer person (`persony-sprzedaz/`) | ✅ czyta persony poprawnie; generowanie przez model nietestowane (brak klucza w tej sesji) |
| `ad_performance_analyzer.py` | Liczy CTR/CPC/CPA i klasyfikuje warianty (pause/scale/keep_testing) | ✅ (na `mock_data/sample_ad_metrics.json`) |
| `ad_test_report.py` | Raport 48h + zadania follow-up w Projectly (pauza żółta, skalowanie czerwone) | ✅ end-to-end na mocku |
| `ad_set_launcher.py` | Uruchamia test reklamowy w ramach bounded red `ad_test_launch` | ✅ bramka bounded_red działa (domyślnie wymaga człowieka); samo wywołanie Meta/TikTok API — stub |
| `mailerlite_client.py` | Konektor MailerLite REST API (kampanie + statystyki) | ⚠️ napisany wg publicznej dokumentacji znalezionej przez wyszukiwarkę (bezpośredni dostęp zablokowany w tej sesji) — zweryfikuj dokładne ścieżki przed produkcją |
| `mailerlite_report_analyzer.py` | Cotygodniowy raport: statystyki, czytelność (heurystyka), ocena tonu/tytułu (model) | ✅ end-to-end na `mock_data/sample_mailerlite_campaigns.json` — poprawnie odróżnia dobry mail od rozwlekłego |
| `digest_generator.py` | Digest z Projectly (zrobione/przeterminowane/w toku) przed daily/weekly — priorytet #2, patrz PLAN-WDROZENIA.md sekcja 10 | ✅ na `mock_data/sample_project_tasks.json`; celowo bez pola realnej daty wykonania (patrz `PROJECTLY-ROZWOJ.md`) |
| `source_schema_watcher.py` | Wykrywa zmianę struktury pliku źródłowego CSV, tworzy zadanie dla właściciela | ✅ end-to-end na `mock_data/source_sample_v1.csv` → `v2_changed.csv` (wykrywa zmianę nazwy i nową kolumnę) |
| `data_contract_validator.py` | Waliduje plik wobec zadeklarowanego kontraktu (`config/data_contracts/*.yaml`) | ✅ na tych samych plikach co watcher — v1 zgodny, v2 niezgodny |
| `stale_time_entry_nudger.py` | Znajduje wpisy czasu "otwarte" dłużej niż próg dni, grupuje wg osoby | ✅ uruchomiony na mocku ORAZ na prawdziwym eksporcie godzin — realnie znalazł 260h zaległych wpisów |
| `report_builder.py` | Generyczny silnik raportów (markdown/CSV) z listy rekordów | ✅ markdown i CSV; `.xlsx` jasny stub (wymaga openpyxl, celowo niezainstalowany) |
| `email_client.py` / `email_draft_generator.py` | Draft/wysyłka maila z szablonu (`templates/email/`), przygotowanie pod Microsoft Graph | ✅ tryb mock (zapis do `runs/mock_outbox/`); **każda wysyłka (`send_email`) przekierowana do `config/email_safety.yaml` (dziś: Paweł/Aldona), nigdy bezpośrednio do zamierzonego adresata** — fail-closed, pusta lista blokuje wysyłkę; realny Graph — stub |
| `task_feedback_requester.py` | Prosi o feedback po zamknięciu zadania: komentarz + zadanie w Projectly + mail | ✅ end-to-end na mocku, w tym idempotencja (nie pyta drugi raz o to samo zadanie, `runs/feedback_requested.json`) |
| `weekly_team_report.py` | Raport tygodniowy zespołu: zrobione/przeterminowane zadania + zaległe wpisy czasu + opcjonalna interpretacja słabych stron (model) | ✅ end-to-end, w tym z prawdziwym eksportem godzin podanym jako `time_entries_csv` |
| `system_health_monitor.py` | Cyklicznie (domyślnie co 2 min) patrzy na RAM i czy oczekiwane skrypty (`runner_loop.py`) faktycznie działają w systemie, publikuje status, eskaluje przy problemie | ✅ obie ścieżki (ok/critical) przetestowane, w tym z realnym odczytem RAM przez `psutil` |
| `env_bootstrap.py` | Centralny loader `.env`/`secrets/.env`, importowany przez każdy moduł czytający klucz API, żeby działał też uruchomiony samodzielnie | ✅ przetestowany, w tym że `secrets/.env` realnie nadpisuje wartość |
| `bootstrap_init_secrets.py` | Tworzy `secrets/.env` i `secrets/mcp/*.json` (na podstawie `integrations.yaml`) — jedno miejsce na wszystkie dostępy | ✅ tworzenie i idempotencja (nigdy nie nadpisuje już wypełnionych plików) przetestowane |
| `bootstrap_install_claude_code.ps1` | Instaluje Claude Code (CLI) natywnym instalatorem | ✅ logika wykrywania przetestowana realnie (w tej sesji Claude Code już jest, więc zadziałała ścieżka "już zainstalowany") |
| `bootstrap_install_claude_desktop.ps1` | Pobiera i uruchamia instalator Claude Desktop | ⚠️ logika poprawna składniowo; samo pobranie nietestowane — `downloads.claude.ai` zablokowane w sieci tej sesji budowy (potwierdzone: 403/policy denial), nie problem kodu |
| `bootstrap_install_python.ps1` | Instaluje Python 3.11+ (winget → fallback: instalator z python.org, cicha instalacja udokumentowanymi przełącznikami) | ⚠️ logika wykrywania przetestowana realnie; samo pobranie z python.org nietestowane (zablokowane w sieci tej sesji budowy, ten sam powód co Claude Desktop) |
| `bootstrap_all.ps1` | Orkiestrator: uruchamia Kroki 2-5 jednym poleceniem, pokazuje numer/nazwę/status/czas trwania każdego kroku, zapisuje historię do `runs/bootstrap_history.json` | ✅ **przetestowany end-to-end realnie** (pełny udany przebieg, wymuszona awaria kroku wymaganego — poprawnie przerywa, `-SkipClaudeCode`) — po drodze złapał i naprawił 2 subtelne błędy PowerShella (zanieczyszczenie wartości zwracanej wyjściem podprocesu, `Format-Table -AutoSize` nic niewypisujące bez prawdziwej konsoli) |
| `machine_status_reporter.py` | Cogodzinny raport statusu maszyny (wersje narzędzi, historia bootstrapu, RAM) do Projectly przez `client.publish_status()` | ✅ przetestowany z i bez historii bootstrapu; wysyłka w trybie mock — czeka na zapowiedzianą dedykowaną funkcję MCP po stronie Projectly |
| `job_scheduler.py` | Centralny scheduler wszystkich skryptów cyklicznych — `config/schedule.yaml`, zmiana harmonogramu na żywo bez restartu, stan w `runs/scheduler_status.json` (`--status`), **każdy przebieg dopisywany do `runs/run_history.jsonl`** (przycinane do 1000 ostatnich) z **przechwyconym pełnym wyjściem (stdout+stderr) i zwróconą wartością** zadania, `run_job_by_name()` odpala jedno zadanie na żądanie, `get_run_log(id)` zwraca szczegół przebiegu | ✅ **przetestowany na żywo, wielowątkowo, z prawdziwymi zadaniami** (odpalane równolegle wg różnych interwałów) i z celowo zepsutym zadaniem (poprawnie raportuje błąd, nie wywraca schedulera); historia, przechwytywanie wyjścia i uruchamianie na żądanie pokryte `dashboard_smoke_test.py` |
| `dashboard.py` + `dashboard.html` | Okno w przeglądarce (`python dashboard.py` → `http://127.0.0.1:8787/`): pełna szerokość ekranu, rozsuwane kolumny (zapamiętywane), lista skryptów z opisem, edycja harmonogramu (interwał / włącz-wyłącz / opis), „uruchom teraz”, historia przebiegów oraz **klik w przebieg → okno z pełnym wyjściem skryptu i zwróconą wartością** (`/api/run-log`). Mały serwer na bibliotece standardowej (http.server), zero nowych zależności, słucha tylko na localhost | ✅ logika (edycja, historia, uruchamianie na żądanie, walidacja, endpoint szczegółu) pokryta `dashboard_smoke_test.py` + żywy test HTTP |

## Mini-zestaw autonomiczny (M2b) — działa lokalnie i na VM

Najmniejszy samodzielny zestaw: pętla chodzi sama, robi realną pracę, każdą decyzję odkłada w historii i widać ją na żywo.

| Element | Co robi | Test |
|---|---|---|
| `env_bootstrap.py` (shim UTF-8) | Wymusza UTF-8 na stdout/stderr — bez tego konsola Windows (cp1250) wywala się na emoji w komentarzach/statusach i ubija runner. Importowane przez każdy punkt wejścia + `job_scheduler.py`. | ✅ potwierdzone: przed fixem `UnicodeEncodeError`, po — pełny przebieg |
| `executor.py` | Pierwszy realny worker (nie stub): walidacja struktury PBIP (read-only, zielone) z pełnym raportem (co sprawdzono, ile plików, błędy/ostrzeżenia). Ścieżka zadania ograniczona do `ALLOWED_ROOTS` — worker odmawia plików spoza workspace (fail-closed, zalążek kontraktu uprawnień M1). Franek dostaje `functional_checks` (typ `pbip_valid`), Bartek `rerun` (kontrola determinizmu). | ✅ `flows_smoke_test.py` (walidacja przechodzi + odmowa ścieżki spoza workspace) |
| `state_store.log_decision()` + migracja `events` | Każda decyzja agenta (kto/co/**dlaczego**/model/koszt/czas) trafia do append-only `events` w `state.db`. Kolumny dokładane migracją (`_migrate`) — wstecznie zgodne z żywą bazą. `get_recent_decisions()` zasila zakładkę Przepływy. | ✅ `flows_smoke_test.py` (log → odczyt, pomija zdarzenia techniczne) |
| `runner_loop.py` (wpięcie) | Woła `executor.execute` przed bramką (realna praca zamiast stuba dla PBIP), loguje decyzje na każdym kroku: klasyfikacja (pawel) → wykonanie (patrycja) → bramka (gustaw) → eskalacja (pawel). Odmowa workera = eskalacja bezpieczeństwa z pominięciem bramki. | ✅ pełny przebieg na mocku (PRJ-0005: realna walidacja → przegląd żywym modelem → eskalacja z feedbackiem) |
| `dashboard.py` + `dashboard.html` (zakładka Przepływy) | Endpoint `/api/flows` + widok „Przepływy agentów — decyzje na żywo" (kto → co → dlaczego → model → koszt), odświeżany co 4 s. Tylko localhost. | ✅ `build_flows()` zwraca decyzje z bazy |
| `export_decisions.py` | Zrzut historii decyzji z `state.db` do CSV/JSONL (opcjonalnie `--since`) do analizy offline i dopracowywania skilli. Nic nie kasuje. | ✅ `flows_smoke_test.py` |
| `notebook_intake.py` + `inbox/zadania.txt` | Dodatkowa LOKALNA ścieżka zadań obok Projectly (intake, PLAN sekcja 11). Wrzucasz linijkę do notatnika (`title`, opcjonalnie `!yellow`/`!red`, `@ ścieżka` dla PBIP), a `notebook_intake` przetwarza ją TYM SAMYM pipeline'em (`runner_loop.process_task`) klientem **mock** — nic nie idzie do żywego Projectly, decyzje widać w Przepływach. Dedup po treści linii (`runs/notebook_processed.json`), notatnika nie modyfikuje. Job w schedulerze (60 s, włączony; pusty notatnik = no-op). CLI: `python notebook_intake.py`. | ✅ `notebook_intake_smoke_test.py` (parse + dedup) |
| `start-agent.bat` + `register-task.ps1` | Autonomiczny start: `job_scheduler.py` (runner co 30 s + monitoring + samo-weryfikacja) jako zadanie w Harmonogramie zadań Windows (wyzwalacz: przy zalogowaniu, bez admina). Przenośne na VM: kopiujesz folder, uruchamiasz `register-task.ps1`. | — (rejestracja przez `powershell -File register-task.ps1`) |

**Uwaga o odbiorze biznesowym:** bramka jest fail-closed — Bożena (obowiązkowa) bez „tak" eskaluje. Przy żywym modelu robi realny, wymagający przegląd; na minimalnej próbce PBIP (1 plik TMDL) zwykle znajduje coś do dopracowania i słusznie eskaluje. To działa zgodnie z projektem, nie jest błędem. Podgląd na żywo: `python dashboard.py` → `http://127.0.0.1:8787/`.

## Czego celowo brakuje (uczciwie, nie udawane)

- **Prawdziwe połączenie z Projectly** (`projectly_client.py`) — endpointy/autoryzacja nie są znane z tej sesji. Domyślnie `MockProjectlyClient` (czyta/pisze pliki w `mock_data/` i `runs/`). Ustaw `PROJECTLY_API_KEY` + `PROJECTLY_BASE_URL`, dopisz metody `ProjectlyClient`.
- **Realne wywołanie modelu w `validator_visual.py`** — kod jest napisany i wywoła prawdziwy model, jeśli podasz `ANTHROPIC_API_KEY` i zrzut ekranu; bez nich zwraca `approved=False` z jasnym wyjaśnieniem, zgodnie z fail-closed. Sama rozmowa z modelem nietestowana z tej sesji (brak klucza) — zweryfikuj na docelowej maszynie z prawdziwym zrzutem.
- **Prawdziwe workery** (Power BI Desktop Bridge + zrzuty, CRM, Meta Ads, SharePoint...) — `runner_loop.py` dziś tylko klasyfikuje i komentuje (`execution_result` to zaślepka), nie wykonuje realnej pracy w tych systemach. `pbip_validate.py` sprawdza tylko warstwę plikową — zrzuty stron wymagają Desktop Bridge na prawdziwym Windows z Power BI Desktop.
- **Realna wysyłka maila** (`email_client.py`) — wymaga rejestracji aplikacji w Azure AD (Microsoft Entra) i pakietu `msal`; do czasu podania `MS_GRAPH_CLIENT_ID/SECRET/TENANT_ID/MAILBOX` w `secrets/.env` działa w trybie mock (draft zapisywany do `runs/mock_outbox/`, nic nie wysyła naprawdę).
- **`bootstrap_install.ps1`** — napisany wiernie wg `SKALOWANIE.md`, ale nieprzetestowany (środowisko budowy to Linux bez dostępu do docelowego Windows). Sprawdź krok po kroku przy pierwszym użyciu.

## Jak uruchomić lokalnie (Python 3.9+, zero kluczy API na start)

```bash
pip install -r requirements.txt
python bootstrap_init_secrets.py           # tworzy secrets/.env + secrets/mcp/*.json — uzupełnij ręcznie, gdy klucze będą znane
python runner_loop.py                     # jeden przebieg na mock_data/sample_tasks.json
python runner_loop.py --loop               # ciągła pętla co 30s (Ctrl+C żeby zatrzymać)
python system_health_monitor.py --loop     # druga, niezależna pętla: RAM + czy runner faktycznie działa (co 2 min)
python bootstrap_smoke_test.py             # pełny test dymny (cykl + heartbeat + kill switch)
python bootstrap_register.py dev           # rejestracja roli
python pbip_validate.py mock_data/sample_pbip   # walidacja przykładowego PBIP
```

Stan w `runs/state.db`, heartbeat w `runs/heartbeat.json` — folder `runs/` jest w `.gitignore` (stan lokalny, nie kod — `SKALOWANIE.md` sekcja 2).

## Co jeszcze będzie potrzebne (pakiety i narzędzia wg fazy)

`requirements.txt` ma dziś tylko to, czego kod faktycznie używa (PyYAML, python-dotenv, anthropic). Reszta jest tam wypisana w komentarzu, żeby nie instalować pakietów, których jeszcze nic nie używa (ten sam problem co przedwczesny rozrost zakresu, tylko na poziomie zależności) — dodawaj je, gdy realnie piszesz danego workera:

| Faza / worker | Pakiety Python | Poza-pythonowe (system/konto) |
|---|---|---|
| Już teraz | PyYAML, python-dotenv, anthropic | — |
| Prawdziwe Projectly (`projectly_client.py`) | `requests` (albo SDK Projectly, jeśli istnieje) | Klucz API Projectly, dokumentacja endpointów |
| Power BI (Faza 3, zrzuty stron) | — (Bridge to nie pakiet pip) | **Power BI Desktop**, ewentualnie Tabular Editor/DAX Studio (opcjonalnie, do pracy nad modelem) |
| Screenshoty/diff (`screenshot_diff.py`) | `Pillow` | — |
| Przeglądarka (Meta Ads UI fallback, CRM UI) | `playwright` + `playwright install chromium` | — |
| Dane/raporty (`data_tidy.py`, `report_builder.py`, watcher schematu) | `pandas`, `openpyxl` | — |
| Google Workspace / Search Console / Analytics | `google-api-python-client`, `google-auth-oauthlib` | Konto serwisowe Google Cloud z odpowiednimi scope'ami |
| SharePoint / Microsoft Graph | `msal` | Rejestracja aplikacji w Azure AD (Microsoft Entra) |
| inFakt | `requests` | Dedykowane konto bota w inFakt, klucz API |
| Orkiestrator / Claude Code na docelowej maszynie | — (osobny CLI, nie pakiet pip) | Node.js (Claude Code jest dystrybuowany przez npm), klucz Anthropic API |
| Zdalny dostęp administracyjny | — | Tailscale (dokumentacja bazowa rozdz. 10.1) |

## Konfiguracja firmy — osobno od kodu

`config/approval_policy.yaml`, `config/clients_routing.yaml`, `config/skills_manifest.yaml`, `config/integrations.yaml` to "konfiguracja firmy" (`SKALOWANIE.md` sekcja 2) — edytowalne bez zmiany kodu, wymieniane przy kopiowaniu do innej firmy. `approval_policy.yaml` ma celowo **pustą** listę `bounded_red` — nie dodawaj tam nic, dopóki zwykły tryb czerwony nie przepracował na produkcji kilku tygodni (sekcja 3 planu).

`config/integrations.yaml` to jeden, konsolidowany rejestr wszystkich dostępnych kont/połączeń (Microsoft 365, Google, Zoho CRM, Projectly, zanfia.com, GitHub, OneDrive, Miro, MailerLite, TikTok Ads, lokalny model Hermes...) — mechanizm, poziom dostępu i uwagi, **nigdy klucze/tokeny** (te w `secrets/` — patrz `bootstrap_init_secrets.py` niżej, tworzy ten folder automatycznie z szablonami MCP na podstawie tego właśnie pliku).

**Ważne rozróżnienie: rejestracja w `integrations.yaml` ≠ istniejący konektor.** Dla większości nowych integracji jest dziś tylko wpis w tym pliku, nie ma jeszcze skryptu, który się z nimi łączy — `SKRYPTY.md` (kategorie F, H, I, O, P) oznacza je jawnie jako "nie napisany jeszcze": `zoho_crm_client.py`, `microsoft_graph_mail_client.py`, `google_workspace_client.py`, `zanfia_client.py`, `miro_read_client.py` (`mailerlite_client.py` jest już napisany, patrz tabela wyżej). Do każdego z nich potrzebny będzie też **skill** (wiedza jak dobrze z tego korzystać, nie tylko hydraulika) — planowane skille wypisane w `config/skills_manifest.yaml` ze statusem `"planned"`.

## Instalacja na docelowym komputerze (Windows)

**Uwaga dla każdego, kto edytuje pliki `.ps1` w tym repo:** zapisuj je z BOM (UTF-8 with BOM), nie zwykłym UTF-8. Bez BOM, Windows PowerShell 5.1 czyta plik w starej stronie kodowej systemu zamiast UTF-8 — polskie znaki i myślniki się rozjeżdżają, a w najgorszym razie łamie to parser w środku stringa (realnie napotkane i naprawione w tej sesji — patrz historia commitów). Edytory typu VS Code robią to poprawnie same, jeśli plik już ma BOM; nowy plik trzeba zapisać świadomie jako "UTF-8 with BOM".

Pełna specyfikacja: `../SKALOWANIE.md` sekcja 4, instruktaż krok po kroku: `../INSTRUKCJA-WDROZENIA.md`. Skrót:

```powershell
# Szybka ścieżka — jedno polecenie zamiast kroków 1-4 niżej (repo domyślne
# z config/repo.yaml; -RepoUrl tylko gdy używasz forka; -WithLocalModel dorzuca
# lokalny model AI sterujący ekranem):
.\bootstrap_all.ps1
.\bootstrap_all.ps1 -WithLocalModel        # jw. + lokalny model wizyjny (Ollama, kilka GB)

# Albo krok po kroku, ten sam efekt:
.\bootstrap_install_git.ps1                # jeśli świeża maszyna/Windows Server nie ma jeszcze gita
.\bootstrap_install_python.ps1             # jeśli nie ma jeszcze Pythona 3.11+
.\bootstrap_install_claude_code.ps1        # narzędzie terminalowe do dalszej pracy nad tym kodem
.\bootstrap_install.ps1                    # -RepoUrl tylko przy własnym forku
.\bootstrap_install_local_model.ps1        # opcjonalnie: lokalny model AI sterujący ekranem (computer use)
python bootstrap_init_secrets.py           # tworzy secrets/.env + secrets/mcp/*.json — uzupełnij ręcznie
python bootstrap_register.py dev
python bootstrap_smoke_test.py

# Uruchomienie na stałe — jedno zadanie w Harmonogramie zadań Windows:
#   Program: python   Argumenty: job_scheduler.py   Rozpocznij w: ...\wirtualny-pracownik\app
python job_scheduler.py --status           # podgląd stanu wszystkich zadań cyklicznych w dowolnej chwili
python dashboard.py                        # okno w przeglądarce: podgląd przebiegów + edycja harmonogramów
```

## Następny krok

Ten kod jest gotowy, żeby lokalny Claude Code (albo inny agent) na docelowym komputerze go przejął i dokończył: podłączył prawdziwe Projectly i klucze, dodał realne wywołanie modelu w `validator_visual.py`, i pierwszy prawdziwy worker (najlepiej dalsza część PBI-01 — zrzuty stron przez Desktop Bridge, skoro walidacja struktury już działa).
