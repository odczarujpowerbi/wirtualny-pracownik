# Monitorowanie agentów AI — plan wdrożenia (strona: Wirtualny Pracownik)

Ten plik to **jeden z dwóch spójnych planów** (drugi: `PLAN-MONITOROWANIE-AGENTOW-PROJECTLY.md`, ten sam folder — plan dla aplikacji Projectly, wdrażany osobno przez właściciela). Oba pliki celowo trzymają identyczny kontrakt danych w sekcji 1, żeby nie rozjechały się w trakcie wdrożenia.

Status: **wdrożone i przetestowane na żywo na produkcji (22.08.2026)**, branch `feat/monitorowanie-agentow` (PR jeszcze niescalony — base powinien być `feat/browser-worker`, nie `main`, bo main jest daleko w tyle). Zobacz sekcję 14 (wynik testów) na końcu.

## 0. Kontekst — po co to i co dziś nie działa

Dziś status agenta trafia do Projectly przez **`ProjectlyClient.publish_status()`** (`app/projectly_client.py`), które woła MCP `create_documentation` / `update_documentation` i nadpisuje jedną stronę dokumentacji per rola bota (tytuł „Status na żywo — {role}”, patrz `app/config/projectly.yaml → live_status.page_title_template`). To dokładnie ten wzorzec, który ma zniknąć: **status live nie jest dokumentacją projektu**, tylko osobnym, ulotnym stanem operacyjnym.

**Cztery** miejsca dziś korzystają z `publish_status(role, payload)` — **każde wysyła inny kształt payloadu**:

| Wywołujący | Rola (string) | Kształt payloadu (dziś) | Częstotliwość |
|---|---|---|---|
| `app/live_status_publisher.py` | rola z `config/role.json` (dziś: `dev`) | `role, machine, updated_at, current_task_id, queue_depth, needs_approval_count, cost_today_usd, cost_limit_usd, health` | co cykl `runner_loop.py` (docelowo 1–2 min, jak `watchdog.py`) |
| `app/machine_status_reporter.py` | `machine-status` | `timestamp, tool_versions, last_bootstrap, ram_available_percent, running_scripts` | co godzinę |
| `app/kacper_monitor.py` | `kacper-monitor` | `events_scanned, repair_tasks_created, checked_at` | przy każdym przebiegu monitora |
| `app/system_health_monitor.py` | `system-health` | `**snapshot (ram itd.), status ("ok"/"warning"/"critical"), issues` | co ~2 min |

**Ważny detal, który kształtuje model danych — nr 1:** `kacper-monitor`, `machine-status` i `system-health` to nie osobne konta w Projectly — działają na tym samym koncie/tokenie co główna rola (np. „dev”) uruchomiona na tej samej maszynie. Dziś rozróżnia je wyłącznie string `role` przekazany do `publish_status`. Nowy model musi to zachować: **jedno konto bota może mieć wiele równoległych, niezależnie nadpisywanych „wierszy” statusu**, po jednym na `role`.

**Ważny detal — nr 2 (korekta po przeczytaniu kodu wszystkich czterech wywołujących):** sztywny kontrakt z jednym zestawem pól (jak w pierwszej wersji tego planu) pasuje tylko do `live_status_publisher.py`. Pozostałe trzy mają zupełnie inne pola i inne znaczenie „status” (np. `system_health_monitor.py`'s `status` to `ok/warning/critical`, nie `working/idle/alert/paused/stopped`). Zamiast zmuszać każdego wywołującego do przepisania swojego payloadu na wspólny kształt, kontrakt (sekcja 1) dostaje pole-worek **`details`** — cały oryginalny payload trafia tam bez strat, a normalizacja (health/status/message) dzieje się **centralnie w `projectly_client.py`**, nie u wywołujących. Dzięki temu teza „zero zmian u wywołujących” (sekcja 2) obejmuje wszystkie cztery moduły, nie tylko trzy.

Cel: master widzi w Projectly, **jak działa każdy agent teraz** (czym się zajmuje, jak długo, czy jest problem) i **jakie były jego ostatnie statusy** — bez grzebania w dokumentacji projektów i bez logowania się na maszynę.

Zakres celowo **read-only**. Sterowanie agentem (pauza/stop) zostaje lokalne, na maszynie (`app/control.py`, `app/dashboard.py` na `127.0.0.1:8787`) — zdalny stop to akcja czerwona i osobny temat bezpieczeństwa, nie wchodzi w ten plan.

## 1. Wspólny kontrakt danych (identyczny w obu planach)

```jsonc
{
  // Etykieta procesu w ramach jednego konta bota. NIE jest tożsamością (tożsamość = token/userId).
  // Wartości dziś w użyciu: "dev", "machine-status", "kacper-monitor". Docelowo też: "marketing",
  // "asystent", "strateg", "admin" (role z ZESPOL-BOTOW.md, gdy powstaną).
  "roleLabel": "dev",

  "status": "working",        // "working" | "idle" | "alert" | "paused" | "stopped"
  "currentTaskId": "task-123",        // opcjonalne
  "currentTaskTitle": "Import godzin z Excela",  // opcjonalne
  "progressLabel": "krok 3/5",        // opcjonalne, wolny tekst

  "queueDepth": 4,             // opcjonalne, liczba zadań w kolejce
  "needsApprovalCount": 1,     // opcjonalne, ile czeka na decyzję człowieka

  "costTodayUsd": 2.35,        // opcjonalne
  "costLimitUsd": 20.0,        // opcjonalne

  "health": "ok",              // "ok" | "alert"
  "healthDetail": null,        // opcjonalny opis alertu

  "message": null,             // opcjonalny wolny tekst -> trafia do historii zdarzeń
  "machine": "WIN-VM-01",      // opcjonalne, nazwa maszyny (platform.node())

  // Worek na wszystko, co nie pasuje do pól wyżej (np. tool_versions, ram_available_percent,
  // repair_tasks_created, issues) — cały ORYGINALNY payload wywołującego, bez strat.
  // UI renderuje to jako zwijany surowy JSON pod kartą agenta.
  "details": { "...": "..." }
}
```

Zasady:
- **Tożsamość = token API**, nie pole w payloadzie. Bot może pisać status tylko dla samego siebie (`ctx.userId` z tokenu), nigdy dla cudzego konta.
- **Jeden wiersz na `(userId, roleLabel)`**, zawsze nadpisywany — nigdy nowy rekord co cykl (zgodnie z pierwotnym założeniem z `PLAN-WDROZENIA.md` §2: „jeden, stały, nigdy niezamykany wpis per bot-rola, nadpisywany”).
- **„Offline” liczy strona odbierająca (Projectly), nie wysyłająca.** Jeśli `updatedAt` starsze niż próg (proponuję 5 minut), UI pokazuje „brak sygnału” niezależnie od ostatniego zapisanego `status`. Agent nie musi nic aktywnie „wypychać” przy awarii — to i tak nie zadziała, jeśli proces padł.
- **Wszystkie pola poza `roleLabel` są opcjonalne.** Brak `status`/`health` nie jest błędem — narzędzie MCP przyjmuje domyślnie `status: "idle"`, `health: "ok"`, gdy pominięte (dotyczy głównie ról pomocniczych: `machine-status`, `kacper-monitor`, `system-health`).

**Zależność:** ten plan zakłada, że narzędzie MCP `post_agent_status` (plan Projectly) jest już wdrożone i działa na produkcji, zanim ten kod zacznie z niego korzystać.

## 2. Zasada nadrzędna: zero zmian u wywołujących

`live_status_publisher.py`, `machine_status_reporter.py`, `kacper_monitor.py` i `system_health_monitor.py` **nie zmieniają się w ogóle** — wszystkie cztery wołają dziś `client.publish_status(role, payload)` i mają dalej wołać dokładnie to samo. Cała zmiana jest ukryta za tą jedną metodą, w `app/projectly_client.py`. To jedyny sposób, żeby przełączenie transportu nie rozjechało czterech miejsc w kodzie naraz.

## 3. `app/projectly_client.py`

- **`ProjectlyClient.publish_status(role, payload)`** — podmienić ciało: zamiast `get_documentation` / `create_documentation` / `update_documentation`, wołać `self.mcp.call_tool("post_agent_status", {"roleLabel": role, **_map_status_payload(payload)})`. Sygnatura metody bez zmian.
- Nowa funkcja pomocnicza **`_map_status_payload(payload: dict) -> dict`** — jedno miejsce normalizacji dla WSZYSTKICH czterech kształtów payloadu (sekcja 0), nie tylko `live_status_publisher.py`:
  - kopiuje 1:1, jeśli obecne: `current_task_id → currentTaskId`, `current_task_title → currentTaskTitle`, `progress_label → progressLabel`, `queue_depth → queueDepth`, `needs_approval_count → needsApprovalCount`, `cost_today_usd → costTodayUsd`, `cost_limit_usd → costLimitUsd`, `machine`, `message`;
  - `health`: `payload["health"]` jeśli już `"ok"/"alert"`; inaczej z `payload["status"]` (`system_health_monitor.py`: `"critical"/"warning"` → `"alert"`, `"ok"` → `"ok"`, fail-closed — niepewne traktujemy jako alert, nie ukrywamy); domyślnie `"ok"`, gdy brak sygnału;
  - `healthDetail`: z `payload["issues"]` (lista → połączona tekstem), jeśli obecne;
  - `status` (aktywność bota, NIE health): przepisywany z `payload["status"]` tylko gdy jest jedną z wartości enuma (`working/idle/alert/paused/stopped`) — inaczej domyślnie `"idle"` (dotyczy ról pomocniczych, których `status` znaczy co innego, np. `ok/warning/critical`);
  - `details`: **zawsze cały oryginalny `payload`** bez zmian — nic nie ginie, nawet pola, których ta funkcja nie rozpoznaje.

  Ta granica mapowania to ten sam wzorzec, co `viability.ts → toViabilityType()` po stronie Projectly — jedno miejsce tłumaczenia konwencji między systemami, tyle że tu dodatkowo pochłania różnorodność kształtów u czterech wywołujących, więc **żaden z nich nie wymaga zmiany kodu** (patrz sekcja 5).
- **`MockProjectlyClient.publish_status`** — zamiast (jak dziś) nadpisywać mockowy JSON w kształcie strony dokumentacji, zapisuje do `app/runs/mock_agent_status.json` w kształcie **identycznym z kontraktem z sekcji 1**, żeby testy w trybie mock realnie sprawdzały ten sam schemat co produkcja.
- **Rollout bez zerowania działającego mechanizmu w trakcie wdrożenia:** dodać krótkotrwałą flagę `config/projectly.yaml → live_status.transport: "documentation" | "agent_status_tool"`, domyślnie `"documentation"` (stare zachowanie) dopóki strona Projectly nie jest potwierdzona na produkcji; potem jedna zmiana defaultu na `"agent_status_tool"` i — po tygodniu/dwóch stabilnej pracy — usunięcie starej gałęzi kodu i samej flagi. Zgodne z zasadą „fail closed” z `CLAUDE.md`: nie robimy skoku na ślepo między dwoma repozytoriami.

## 4. `app/config/projectly.yaml`

- Usunąć `live_status.page_title_template` (nazwa strony dokumentacji, już niepotrzebna) i pole `live_status.project` (status nie jest już przypięty do żadnego projektu Projectly).
- Dodać `mcp_tool_usage.agent_status: post_agent_status`, w stylu istniejącej mapy `mcp_tool_usage` w tym samym pliku.
- Dodać (tymczasowo) `live_status.transport` opisane wyżej.

## 5. `app/live_status_publisher.py`, `app/machine_status_reporter.py`, `app/kacper_monitor.py`, `app/system_health_monitor.py`

**Zero zmian funkcjonalnych w żadnym z czterech** — to bezpośrednia konsekwencja `details`-worka i centralnej normalizacji w `_map_status_payload` (sekcja 3): każdy z tych modułów dalej buduje swój payload dokładnie tak jak dziś i woła `client.publish_status(role, payload)` bez żadnej zmiany wywołania. Jedyna zmiana tekstowa:
- zaktualizować komentarz/docstring w `live_status_publisher.py` — status trafia teraz do dedykowanego API monitorowania, nie do strony dokumentacji,
- w `machine_status_reporter.py` (komentarz „UCZCIWA GRANICA…”) i `system_health_monitor.py` (komentarz o `live_status_publisher.py` jako „jedynym miejscu, które nadpisuje status”) — zaktualizować opis zgodnie z nowym stanem, treść kodu bez zmian.

## 6. `app/watchdog.py`

Bez zmian w tym planie. Wykrywanie „braku sygnału” przenosi się na stronę odbiorczą (Projectly liczy `now - updatedAt`), więc watchdog nie musi nic aktywnie wypychać przy awarii — i tak nie zadziała, jeśli proces padł całkowicie. Istniejący TODO „docelowo: eskalacja do Projectly” w kodzie zostaje jako świadomie odłożony, osobny temat (proaktywny alert / eskalacja czerwona), nie część tego planu.

## 7. Testy

- Nowy/rozszerzony `app/live_status_publisher_smoke_test.py` (konwencja repo: funkcja `run()`, druk ✅/❌, `sys.exit(1)` przy porażce) — podmienia `MCPClient.call_tool` atrapą, sprawdza, że `publish_status` woła `post_agent_status` z payloadem zgodnym z kontraktem (wszystkie wymagane pola, poprawne typy).
- `python app/self_check.py` zielony po zmianie — bramka jakości repo wymagana przed przejściem dalej (`CLAUDE.md`).

## 8. Dokumentacja

- `app/README.md` — zaktualizować opis `live_status_publisher.py` (transport, nie strona dokumentacji).
- `docs/panel-operatora.html` / `docs/architektura.html` (którakolwiek dziś opisuje mechanizm „status na żywo = strona dokumentacji”) — zaktualizować opis + dopisać, że fleet-view na żywo jest teraz w zakładce master „Monitorowanie agentów” w Projectly, a lokalny `dashboard.py` (`127.0.0.1:8787`) zostaje jako podgląd offline/na-maszynie (dwa uzupełniające się widoki, nie zamiennik).

## 9. Pliki do zmiany — podsumowanie

| Plik | Zmiana |
|---|---|
| `app/projectly_client.py` | `publish_status` woła nowe MCP-narzędzie zamiast dokumentacji; + `_map_status_payload`; mock zapisuje w kształcie kontraktu |
| `app/config/projectly.yaml` | usunięcie `page_title_template`/`project` z `live_status`, dodanie `mcp_tool_usage.agent_status`, tymczasowa flaga `transport` |
| `app/live_status_publisher.py` | tylko komentarz/docstring |
| `app/machine_status_reporter.py`, `app/kacper_monitor.py`, `app/system_health_monitor.py` | tylko komentarz — logika bez zmian (patrz `details` w sekcji 3) |
| `app/live_status_publisher_smoke_test.py` | nowy/rozszerzony test |
| `app/README.md`, `docs/panel-operatora.html`/`docs/architektura.html` | aktualizacja opisu |

## 10. Weryfikacja

1. Tryb mock (bez kluczy): `python app/self_check.py` zielony, w tym nowy smoke test.
2. Tryb na żywo (po wdrożeniu strony Projectly na produkcji): `python -c "from app.live_status_publisher import publish; from app.projectly_client import get_client; publish(get_client(), role='dev')"` → sprawdzić w Projectly (`/dashboard/agent-monitoring` jako master), że karta „AI - Dev” pokazuje świeży `updatedAt` i poprawne pola.
3. Uruchomić `python app/runner_loop.py` na jednym zadaniu mock — na końcu cyklu status w Projectly powinien się zaktualizować (jeśli `transport: agent_status_tool` już ustawione).
4. Odciąć na chwilę sieć / unieważnić token → poczekać >5 minut → w zakładce mastera agent pokazuje „brak sygnału” (offline liczony po stronie Projectly, zgodnie z sekcją 1).

## 11. Kolejność między repozytoriami

1. Projectly (drugi plan) — schema + migracja + narzędzie MCP + strona + sidebar. Deploy na Railway.
2. Ręczna weryfikacja Projectly na produkcji zanim ten kod zacznie z niego korzystać.
3. Ten plan — najpierw z flagą `transport: "documentation"` (nic się nie zmienia w zachowaniu), potem przełączenie na `"agent_status_tool"` po potwierdzeniu, że narzędzie MCP odpowiada poprawnie.
4. Po 1–2 tygodniach stabilnej pracy: usunięcie starej gałęzi kodu (dokumentacja-jako-status) i flagi `transport` z `projectly.yaml`.

## 12. Świadomie poza zakresem

- **`digest_generator.py` i `weekly_team_report.py`** — dziś publikują cykliczne podsumowania jako komentarze na sztucznych pseudo-zadaniach (`DIGEST-{project}`, `WEEKLY-TEAM-REPORT`). To osobny, pokrewny anty-wzorzec — wart własnego planu, ale nie wchodzi w ten dokument.
- **Zdalne sterowanie agentem z Projectly** — zakładka jest read-only; kontrola zostaje lokalna.
- **Wielobotowy zespół z `ZESPOL-BOTOW.md`** (Waldek/Krzysztof/Zofia/Zenek/Strateg) — model danych (`roleLabel` per konto) jest już na to gotowy, ale zakładanie kolejnych kont botów to osobna decyzja biznesowa.

## 13. Do potwierdzenia przed startem implementacji

1. Próg „offline” w UI — proponuję 5 minut od `updatedAt`. Zmienić, jeśli cykl publikowania w produkcji będzie inny niż 1–2 min.
2. Czy `post_agent_status` ma być ograniczone wyłącznie do kont `isBot: true` (decyzja po stronie Projectly)?
3. Limit historii zdarzeń na agenta — proponuję 200 wpisów (decyzja po stronie Projectly).

## 14. Wynik testów na żywo (22.08.2026)

Zaimplementowane w izolowanym worktree (`feat/monitorowanie-agentow`, 3 commity), zweryfikowane realnym wywołaniem produkcyjnego `post_agent_status` (`https://projectly-production.up.railway.app/api/mcp`, token konta „AI - Dev”):

- **`tools/list` na produkcji potwierdza `post_agent_status` obecne.** `get_agent_statuses` (P2, sekcja 11 drugiego planu) — nieobecne, zgodnie z oczekiwaniem (opcjonalne, nieblokujące).
- **Rozbieżność wykryta przed wysyłką:** produkcyjny schemat `post_agent_status` **nie ma pola `details`** (worek na resztę danych, zakładany w sekcji 1 obu planów po korekcie) — druga strona wdrożyła wcześniejszą, węższą wersję kontraktu. Wysyłka `details` mimo to **nie failuje** (zod po cichu ignoruje nierozpoznane klucze) — ale bez naprawy role `machine-status` i `kacper-monitor` trafiałyby do dashboardu jako puste wiersze (brak jakiegokolwiek pola poza domyślnym `ok`/`idle`).
- **Naprawiono po stronie agenta**, bez czekania na zmianę schematu: `_map_status_payload` syntetyzuje czytelny `message` z `tool_versions`/`ram_available_percent` (machine-status) i z `events_scanned`/`repair_tasks_created` (kacper-monitor — dodatkowo wymusza `health=alert`, gdy powstało zadanie naprawcze). `details` nadal wysyłane (nieszkodliwe) — gdy Projectly doda to pole, zacznie działać bez zmiany kodu po tej stronie.
- **4/4 realne kształty payloadu przeszły bez błędu MCP na produkcji** (role testowe: `dev-test`, `machine-status-test(-2)`, `kacper-monitor-test(-2)`, `system-health-test`). Te wiersze zostają w bazie Projectly — nieszkodliwe (pokażą się jako „brak sygnału” po 5 min), ale do posprzątania przez mastera (Prisma Studio) jeśli dashboard ma być czysty.
- **Domyślny transport przełączony na `agent_status_tool`** (`config/projectly.yaml`) — potwierdzone działające, nie ma już powodu trzymać starego zachowania jako domyślnego. Legacy ścieżka (`_publish_status_via_documentation`) zostaje w kodzie jako fallback (można wymusić przez config), do usunięcia po okresie stabilizacji.
- **44/44 (39 istniejących + 5 nowych w `live_status_publisher_smoke_test.py`) testów `self_check.py` zielone.**
- **Otwarte dla drugiej strony (Projectly):** rozważyć dodanie pola `details`/`raw` (dowolny JSON) do schematu `post_agent_status` — dziś nieblokujące (obejście działa), ale bez tego każda PRZYSZŁA rola o nieprzewidzianym kształcie payloadu będzie wymagać ręcznej reguły syntezy `message` po stronie agenta, zamiast automatycznie nosić pełne dane.
