# PLAN-VM — handoff dla agenta na maszynie wirtualnej

Ten plik jest instrukcją dla agenta (Claude Code) uruchomionego na VM. Cel: postawić środowisko, podłączyć realne źródła, a potem samodzielnie dokończyć projekt (workery, skille, testy, weryfikacja) w granicach reguł niżej. Właściciel: Paweł. Komunikacja po polsku.

Repo: `https://github.com/odczarujpowerbi/wirtualny-pracownik.git` (branch `main`).

---

## 0. Jak masz pracować (agencie, przeczytaj najpierw)

1. Wczytaj `CLAUDE.md` (reguły projektu) oraz `~/.claude/rules/*` (coding-rules, git-workflow, power-bi-standards). One nadrzędne wobec tego pliku.
2. Tryb pracy: dla każdej większej pozycji z backlogu wejdź w plan mode, przedstaw plan, potem implementuj. Właściciel zaakceptował autonomię W GRANICACH guardrails z sekcji 6, więc drobne, dobrze zdefiniowane kroki rób od razu; przy niejasności PYTAJ, nie zgaduj.
3. Każda zmiana kodu: osobny branch + PR, nigdy bezpośrednio do `main`. Commity numerowane, po polsku, format `NN - opis` (sprawdź ostatni numer: `git log --oneline -1`).
4. Bramka jakości Twojej pracy: `python app/self_check.py` MUSI być zielony przed przejściem do kolejnej pozycji. Każda nowa funkcja: minimum 1 test happy path + 1 error case, jako `app/<nazwa>_smoke_test.py` w konwencji projektu (funkcja `run()`, druk ✅/❌, `sys.exit(1)` przy porażce). Testy muszą być szybkie, bez sieci, bez efektów ubocznych GUI (atrapy/wstrzykiwanie), bo `self_check` odpala je cyklicznie.
5. Pliki runtime (stan, flagi, raporty, zrzuty, cache) TYLKO do `app/runs/` albo `app/secrets/` (oba w `.gitignore`). Nigdy do ścieżki śledzonej przez git. Wartości domyślne trzymaj jako szablon `*.default.*` i seeduj lokalną kopię przy starcie.
6. Fail-closed: przy niepewności zapisz stan i eskaluj, nie wykonuj działań nieodwracalnych. Sekrety nigdy w repo/logach/zrzutach.
7. Multi-agent tylko gdy zadania są niezależne (różne pliki, brak zależności sekwencyjnych). Research/czytanie: Haiku. Implementacja: Sonnet. Planowanie: Opus.
8. Nie modyfikuj istniejących testów, żeby przeszły. Nie osłabiaj asercji. Failujący test = napraw kod. To reguły z coding-rules, egzekwuj je na sobie.

Stan wyjściowy kodu: `app/README.md` (co działa / czego brak). Pokrycie celu i statusy: `docs/przeplyw.html`. Warstwa agenta lokalnego (wizja/OCR/okna/kontekst/koszt) jest już zbudowana i przetestowana logicznie (`self_check` 20/20), ale warstwa GUI nie była uruchamiana na prawdziwym Windows z Power BI.

---

## 1. Faza 0 — postaw VM (runbook)

Cel fazy: środowisko działa, `self_check` i `bootstrap_smoke_test` zielone, dashboard się otwiera.

### 1a. Czysta maszyna (nic nie ma)
PowerShell jako administrator, jedna linia (klonuje repo i uruchamia cały instalator bezobsługowo):
```powershell
$s="$env:TEMP\postaw.ps1"; irm https://raw.githubusercontent.com/odczarujpowerbi/wirtualny-pracownik/main/instalacja/postaw-od-zera.ps1 -OutFile $s; powershell -ExecutionPolicy Bypass -File $s
```
Domyślnie klonuje do `%USERPROFILE%\wirtualny-pracownik`. Opcje: `-InstallPath`, `-RepoUrl`, `-Branch`, `-SkipOffice`, `-SkipLocalModel`, `-SkipLogins`.

### 1b. Repo już jest
Dwuklik `instalacja\Przygotuj-srodowisko.bat` (na świeżej maszynie: prawy → Uruchom jako administrator).

### 1c. Logowania (raz, interaktywnie)
Dwuklik `instalacja\Zaloguj.bat`. Obejmuje: Claude Code (`claude` → subskrypcja), Microsoft 365, aktywacja Office, Google, Meta Business, GitHub, VS Code. Stan w `app/runs/logins_status.json`.

### 1d. Sekrety
Uzupełnij `app/secrets/.env` (utworzony przez `bootstrap_init_secrets.py`). Klucze wg `app/config/integrations.yaml`. Nigdy nie commituj `secrets/`.

### 1e. Weryfikacja fazy 0
```bash
cd app
python self_check.py            # oczekiwane: wszystkie testy zielone
python bootstrap_smoke_test.py  # pełny cykl + heartbeat + kill switch
python runner_loop.py           # jeden przebieg na mock_data
python dashboard.py             # http://127.0.0.1:8787/  (podgląd)
```
Definicja ukończenia: wszystkie cztery przechodzą, autostart (`job_scheduler.py`) zarejestrowany.

---

## 2. Faza 1 — podłącz realne źródła (odblokowuje resztę)

Kolejność ma znaczenie: bez realnej kolejki zadań i modelu reszta jest ślepa.

| # | Zadanie | Definicja ukończenia (DoD) |
|---|---|---|
| 1.1 | **Realny Projectly przez MCP** (`app/projectly_client.py` klasa `ProjectlyClient`, `app/mcp_client.py`). Ustaw `PROJECTLY_API_KEY` + `PROJECTLY_BASE_URL`, zweryfikuj każdą metodę wobec prawdziwego MCP (mapa w docstringu klienta i `config/projectly.yaml`). | `get_new_tasks` zwraca realne zadania, `post_comment`/`update_status`/`create_task` działają na prawdziwym koncie AI; smoke test z atrapą MCP + jeden ręczny test na żywo. |
| 1.2 | **Model decydenta**: `claude login` w terminalu (subskrypcja). Opcjonalnie `ANTHROPIC_API_KEY` (fallback SDK) i Ollama (druga opinia). | `python task_thinker.py` zwraca realną analizę; `env_report` widzi `claude`. |
| 1.3 | **OCR na maszynie**: zainstaluj binarkę Tesseract + pakiety językowe `pol`, `eng`, dodaj do PATH. | `python ocr_extract.py <zrzut>` zwraca `available: True, source: tesseract`. |
| 1.4 | **Zależności agenta lokalnego**: `pip install mss Pillow pytesseract pygetwindow pywinauto`. | `python window_manager.py` listuje okna; `python screenshot_capture.py` zapisuje zrzut do `runs/screenshots/`. |
| 1.5 | **Realna wysyłka maila** (Microsoft Graph): rejestracja aplikacji Azure AD, `MS_GRAPH_*` w secrets, flaga `GRAPH_SEND_IMPLEMENTED`. | `graph_mail_smoke_test.py` zielony na żywo; każda wysyłka nadal przekierowana przez `email_safety.yaml`. |

Po każdym podpunkcie: `self_check` zielony, zanim idziesz dalej.

**1.6 Zestaw skilli/pluginów/agentów (`~/.claude`).** Po zalogowaniu (OneDrive zsynchronizowany + `claude login`) uruchom `instalacja\skrypty\bootstrap_install_claude_assets.ps1` (robi to też automatycznie koniec `Zaloguj.bat`). Kopiuje ~45 skilli i agentów ogólnych z biblioteki OneDrive `Aplikacje Claude - Documents` do `~/.claude` i instaluje pluginy przez marketplace (power-bi-agentic-development, claude-plugins-official, claude-powerline, oaustegard-claude-skills). **Buyer persony (Odczaruj i Clickless) zostają per-projekt** w folderach `Buyer persony ...` (mają kolidujące nazwy, np. `persona-tomek`) i są na VM przez sync OneDrive — używasz ich pracując w danym projekcie, nie globalnie.

---

## 3. Faza 2 — domknij pętlę wizyjną Power BI (pierwszy realny worker z efektem)

To jest krytyczny milestone: pierwszy pełny łańcuch praca → efekt → weryfikacja na prawdziwym systemie.

- 2.1 Zweryfikuj `app/pbi_desktop_bridge.py` na PRAWDZIWYM Power BI Desktop: otwarcie PBIP, wykrycie okna (`PBI_WINDOW_TITLE`), zrzut strony. Dostrój `title_hint` i `wait_seconds` do realnego czasu renderu.
- 2.2 E2E na żywo: zadanie `action: open_pbip_capture` z `project_path` w `app/workspace/` przechodzi przez `executor` → `screenshot_path` → bramka (Oskar ocenia zrzut, OCR konfrontuje liczby) → status.
- 2.3 Dodaj `screenshot_diff.py` (Pillow) do Bartka: porównanie zrzutu przed/po dla regresji wizualnej.

DoD: realne zadanie PBI kończy się zrzutem strony ocenionym przez bramkę; wynik widoczny w dashboardzie (Przepływy).

---

## 4. Faza 3 — workery na gotowym substracie (computer use i przeglądarka)

Substrat gotowy: `screenshot_capture`, `window_manager`, `ui_lock` (serializacja: jedno aktywne okno na zadanie), `ocr_extract`, `file_search`.

| # | Skrypt do napisania | Odpowiedzialność | DoD |
|---|---|---|---|
| 3.1 | `browser_worker.py` (Playwright) | Zadania webowe: nawigacja, klik, wypełnienie, zrzut. `playwright install chromium`. | Wykonuje zdefiniowane kroki na stronie testowej, produkuje `screenshot_path`; smoke test na lokalnym HTML. |
| 3.2 | `computer_use_worker.py` | Pętla zobacz → decyzja modelu → klik → zweryfikuj (zrzut + OCR), z blokadą `ui_lock` (sekwencyjnie). | Wykonuje prostą operację w aplikacji desktopowej pod nadzorem; przy niepewności eskaluje. |
| 3.3 | Wpięcie w `executor.py` | Nowe akcje + kontrakty w `config/tool_contracts.yaml` (fail-closed, allowed_roots). | Zadanie danego typu przechodzi bramkę; test wpięcia z atrapą (jak `executor_capture_smoke_test.py`). |

Zasada: computer use i przeglądarka trzymają fokus sekwencyjnie (`ui_lock`); równolegle idą tylko zadania plikowe.

---

## 5. Faza 4 — skille i konektory (model: skill wyzwala skrypt i patrzy na output)

Każda pozycja to para: skill (wiedza JAK dobrze użyć) + skrypt/konektor (hydraulika) + test. Rejestr skilli: `config/skills_manifest.yaml` (status `planned` = do napisania). Rejestr integracji: `config/integrations.yaml`.

Priorytet (od rdzenia komunikacji w dół):

| # | Skill (manifest) | Skrypt/konektor do napisania | DoD |
|---|---|---|---|
| 4.1 | `projectly_operations` | (klient z fazy 1.1) + wzorce pracy | Skill opisuje schemat zadania, tworzenie/aktualizację/komentarze/statusy; realny przebieg zadania end-to-end przez Projectly. |
| 4.2 | `microsoft_graph_operations` | `microsoft_graph_mail_client.py` (dokończenie realnej wysyłki) + SharePoint/OneDrive | Odczyt/wysyłka z jednego konta, przekierowanie bezpieczeństwa; smoke bez sieci + jeden test na żywo. |
| 4.3 | `zoho_crm_operations` | `zoho_crm_client.py` (MCP: COQL, rekordy, tagi) | Odczyt rekordów i aktualizacja statusu klienta; test na atrapie MCP. |
| 4.4 | `google_workspace_operations` | `google_workspace_client.py` (Docs/Sheets/Drive, Search Console/Analytics) | Raport widoczności z realnego źródła; scope minimalny. |
| 4.5 | `mailerlite_operations` | (`mailerlite_client.py` istnieje) — zweryfikuj ścieżki API, dopisz skill | Kampanie vs automatyzacje rozróżnione; statystyki na żywo. |
| 4.6 | `ads_platforms_operations` | wspólny wzorzec Meta/TikTok Ads (odczyt, zmiana budżetu w granicach bounded red) | Zmiana budżetu tylko w `bounded_red` z `approval_policy.yaml`; poza granicą eskaluje. |
| 4.7 | `zanfia_courses_operations`, `miro_read_operations` | `zanfia_client.py`, `miro_read_client.py` (tylko odczyt) | Wyciąga kontekst/dane sprzedażowe; read-only, zielone. |

Dodatkowo skrypty pomocnicze z audytu architektury (napisz, gdy potrzebne): `task_brief_builder` (jest), `screenshot_diff.py`, `routing_confidence_check.py` (egzekucja eskalacji przy niepewnym routingu — wymaga decyzji właściciela o progach, PYTAJ).

---

## 6. Guardrails i governance (czego przestrzegasz zawsze)

- Klasyfikacja ryzyka: **zielone** = auto; **żółte** = auto w granicach polityki z 3 walidatorami/bramką; **czerwone** = zawsze człowiek. Kolor wynika z akcji (`config/approval_policy.yaml`) i treści zadania (`risk_hint.py`).
- Hierarchia metod wykonania: API/MCP → CLI/skrypt → automatyzacja UI → computer use. Zawsze wybieraj najwyższą dostępną.
- Kill switch (`kill_switch.py`) i dzienny limit kosztu (`cost_tracker.py` + `cost_estimator.py`) są aktywne. Nie obchodź ich.
- Każda wysyłka maila przekierowana przez `config/email_safety.yaml`. Operacje na bazie: tylko SELECT, chyba że jawnie zlecone.
- Zmiany w kodzie/PBIP: branch + PR. reviewer i explorer: tylko Read/Grep/Glob.
- Sekrety: `app/secrets/` (nigdy w repo/logach/zrzutach). Waliduj każdy input na granicy (Zod/Pydantic/kontrakt narzędzia).

---

## 7. Backlog uszeregowany (pracuj z góry na dół, DoD w sekcjach wyżej)

1. Faza 0 (postaw VM) — środowisko zielone.
2. 1.1 Realny Projectly (kolejka zadań).
3. 1.2–1.4 Model + OCR + zależności agenta lokalnego.
4. Faza 2 — pętla wizyjna Power BI na żywo.
5. 4.1 `projectly_operations` + pierwsze realne zadanie end-to-end przez Projectly.
6. 1.5 + 4.2 Microsoft Graph (mail/SharePoint).
7. Faza 3 — `browser_worker.py`, potem `computer_use_worker.py`.
8. 4.3–4.7 kolejne skille/konektory wg realnej potrzeby biznesowej.
9. Twarde testy E2E per worker + rozbudowa `self_check`.

Nie rób kroku N+1, dopóki N nie ma zielonego `self_check` i (dla zmian kodu) otwartego PR.

---

## 8. Kickoff — prompt startowy dla właściciela do wklejenia agentowi na VM

> Jesteś agentem tego repo. Przeczytaj `CLAUDE.md`, `~/.claude/rules/*`, `app/README.md`, `docs/przeplyw.html` i `PLAN-VM.md`. Potwierdź stan: uruchom `python app/self_check.py` i podaj wynik. Następnie realizuj `PLAN-VM.md` od pierwszej niezrobionej pozycji backlogu (sekcja 7). Dla każdej pozycji: plan mode → mój akceptacja → implementacja na branchu → testy (`self_check` zielony) → PR z numerowanym commitem. Trzymaj guardrails z sekcji 6. Przy niejasności PYTAJ, nie zgaduj. Raportuj po każdej ukończonej pozycji: co zrobione, wynik testów, co następne.

---

## 9. Definicja „gotowe, mogę pracować na VM"

- `self_check` i `bootstrap_smoke_test` zielone; `job_scheduler.py` startuje automatycznie; dashboard działa.
- Realny Projectly podłączony: agent pobiera i komentuje prawdziwe zadania.
- Co najmniej jeden realny worker z efektem działa end-to-end na żywo (PBI: otwarcie + zrzut + bramka).
- Sekrety uzupełnione, logowania potwierdzone (`logins_status.json`).
- Agent pracuje w pętli, każdą decyzję odkłada w `state.db`, widać ją w Przepływach.
