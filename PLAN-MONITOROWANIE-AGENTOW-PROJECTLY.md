# Monitorowanie agentów AI — plan wdrożenia (strona: Projectly)

Ten plik to **jeden z dwóch spójnych planów** (drugi: `PLAN-MONITOROWANIE-AGENTOW-WIRTUALNY-PRACOWNIK.md`, ten sam folder — plan dla agenta Python, wdrażany po tym planie). Oba pliki celowo trzymają identyczny kontrakt danych w sekcji 1, żeby nie rozjechały się w trakcie wdrożenia.

**Ten plik dotyczy repozytorium Projectly** (`Zarządzanie projektami`, Next.js 15 + Prisma), a nie repozytorium `wirtualny-pracownik` — leży tu tylko dlatego, że oba plany mają być w jednym miejscu do przejrzenia. Wdrożenie tego planu wykonuje właściciel we własnym repo.

Status: narzędzie `post_agent_status` już działa na produkcji (potwierdzone testem na żywo 22.08.2026 z drugiej strony — zobacz `PLAN-MONITOROWANIE-AGENTOW-WIRTUALNY-PRACOWNIK.md` sekcja 14). **Jedna rozbieżność wykryta testem:** wdrożony schemat nie ma pola `details` (sekcja 1 niżej) — zod je po cichu ignoruje (nie failuje), ale role bez własnych rozpoznanych pól (`machine-status`, `kacper-monitor`) tracą swoje dane, dopóki agent nie zsyntetyzuje ich ręcznie do `message` (już zrobione po tamtej stronie jako obejście). Rekomendacja: dodać `details: z.record(z.string(), z.unknown()).optional()` do schematu i zapisać je w `AgentStatus.details` (sekcja 2) — nieblokujące, ale usuwa potrzebę ręcznych reguł syntezy dla każdej nowej roli w przyszłości.

## 0. Kontekst — po co to i co dziś nie działa

Dziś status agenta trafia do Projectly przez `ProjectlyClient.publish_status()` (po stronie Wirtualnego Pracownika), które woła MCP `create_documentation` / `update_documentation` i nadpisuje jedną stronę dokumentacji per rola bota. To dokładnie ten wzorzec, który ma zniknąć: **status live nie jest dokumentacją projektu**, tylko osobnym, ulotnym stanem operacyjnym.

**Ważny detal — nr 1:** jedno konto bota w Projectly (jeden token API) może dziś publikować status pod kilkoma różnymi „rolami” jednocześnie — np. `dev` (główny proces), `kacper-monitor`, `machine-status`, `system-health` — wszystkie z tego samego konta/tokenu, rozróżnione tylko stringiem roli. Model danych musi to wspierać: **jedno konto bota → wiele niezależnie nadpisywanych „wierszy” statusu, po jednym na rolę**.

**Ważny detal — nr 2:** te cztery role wysyłają dziś **zupełnie różne kształty payloadu** (agent roboczy: bieżące zadanie/kolejka/koszt; monitor maszyny: wersje narzędzi/RAM; Kacper: liczba zdarzeń/zadań naprawczych; health systemu: `ok/warning/critical` + lista problemów). Narzędzie MCP nie może wymuszać jednego sztywnego kształtu — patrz pole `details` w kontrakcie (sekcja 1) i model danych (sekcja 2).

Cel: master widzi w Projectly, **jak działa każdy agent teraz** (czym się zajmuje, jak długo, czy jest problem) i **jakie były jego ostatnie statusy** — bez grzebania w dokumentacji projektów.

Zakładka jest **wyłącznie dla roli `master`** (rola realnie istnieje w kodzie — `src/lib/types.ts: UserRole = "admin" | "manager" | "member" | "master"` — nie tylko w dokumentacji). Konta agentów AI mają dziś `role: "member"` (`prisma/ensure-bots.ts`), więc **automatycznie nigdy nie zobaczą** tej zakładki — nie trzeba dodatkowego wykluczenia po `isBot`.

Zakres celowo **read-only**. Sterowanie agentem zostaje po stronie Wirtualnego Pracownika (lokalnie na maszynie) — to osobny temat bezpieczeństwa, nie wchodzi w ten plan.

## 1. Wspólny kontrakt danych (identyczny w obu planach)

```jsonc
{
  // Etykieta procesu w ramach jednego konta bota. NIE jest tożsamością (tożsamość = token/userId).
  // Wartości dziś w użyciu: "dev", "machine-status", "kacper-monitor". Docelowo też: "marketing",
  // "asystent", "strateg", "admin" (przyszłe role wielobotowe).
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
  "machine": "WIN-VM-01",      // opcjonalne, nazwa maszyny

  // Worek na wszystko, co nie pasuje do pól wyżej (np. tool_versions, ram_available_percent,
  // repair_tasks_created, issues) — cały ORYGINALNY payload wywołującego, bez strat.
  // UI renderuje to jako zwijany surowy JSON pod kartą agenta.
  "details": { "...": "..." }
}
```

Zasady:
- **Tożsamość = token API**, nie pole w payloadzie. Bot może pisać status tylko dla samego siebie (`ctx.userId` z tokenu), nigdy dla cudzego konta.
- **Jeden wiersz na `(userId, roleLabel)`**, zawsze nadpisywany — nigdy nowy rekord co cykl.
- **„Offline” liczy strona odbierająca (Projectly), nie wysyłająca.** Jeśli `updatedAt` starsze niż próg (proponuję 5 minut), UI pokazuje „brak sygnału” niezależnie od ostatniego zapisanego `status`.
- **Wszystkie pola poza `roleLabel` są opcjonalne** — zod-schema narzędzia MCP musi to odzwierciedlać (`status`/`health` z wartościami domyślnymi `"idle"`/`"ok"`, gdy pominięte). Dotyczy to głównie ról pomocniczych (`machine-status`, `kacper-monitor`, `system-health`), które nie mają pojęcia „bieżące zadanie” w takim sensie jak główny agent.

## 2. Model danych (`prisma/schema.prisma`)

```prisma
model AgentStatus {
  id                 String   @id @default(cuid())
  userId             String
  roleLabel          String
  status             String   @default("idle")
  machine            String?
  currentTaskId      String?
  currentTaskTitle   String?
  progressLabel      String?
  queueDepth         Int?
  needsApprovalCount Int?
  costTodayUsd       Float?
  costLimitUsd       Float?
  health             String   @default("ok")
  healthDetail       String?  @db.Text
  details            Json?
  updatedAt          DateTime @default(now()) @updatedAt

  user   User               @relation(fields: [userId], references: [id], onDelete: Cascade)
  events AgentStatusEvent[]

  @@unique([userId, roleLabel])
  @@index([userId])
}

model AgentStatusEvent {
  id            String   @id @default(cuid())
  agentStatusId String
  status        String
  message       String?  @db.Text
  createdAt     DateTime @default(now())

  agentStatus AgentStatus @relation(fields: [agentStatusId], references: [id], onDelete: Cascade)

  @@index([agentStatusId, createdAt])
}
```

Na `User` dodać relację `agentStatuses AgentStatus[]`. Migracja: `npx prisma migrate dev --name add-agent-status-monitoring`.

Historia zdarzeń (`AgentStatusEvent`) to lekki dziennik „co się ostatnio działo” pod ten konkretny wiersz — **przycinany przy każdym zapisie do ostatnich ~200 wpisów na `agentStatusId`** (usunięcie starszych w tej samej transakcji co insert). Nie duplikujemy pełnego audytu z lokalnego `state_store.py` po stronie agenta — to tylko podgląd dla mastera, nie źródło prawdy.

## 3. Nowe narzędzie MCP: `post_agent_status`

Wzorzec identyczny jak istniejące narzędzia (`src/lib/mcp/server.ts`, `src/lib/mcp/write.ts`):

1. **`src/lib/mcp/agent-status.ts`** (nowy plik) — `postAgentStatusViaApi(ctx: ApiContext, input: PostAgentStatusInput)`:
   - opcjonalnie: sprawdź, że `ctx.userId` należy do konta z `isBot: true` (rzuć `ApiAccessError`, jeśli nie),
   - `db.agentStatus.upsert({ where: { userId_roleLabel: { userId: ctx.userId, roleLabel } }, ... })`,
   - `db.agentStatusEvent.create(...)` + przycięcie starszych wpisów powyżej ~200 dla tego `agentStatusId`.
2. **`src/lib/mcp/server.ts`** — rejestracja narzędzia z zod-schemą 1:1 z kontraktem z sekcji 1: `roleLabel` wymagane (string, 1-40 znaków), reszta opcjonalna — w tym `details: z.record(z.string(), z.unknown()).optional()` (dowolny JSON, bez tego czterech wywołujących po stronie agenta traci dane, patrz „Ważny detal — nr 2” w sekcji 0). Handler: `run(() => postAgentStatusViaApi(ctxFromAuth(authInfo), args))`.
3. **`get_agent_statuses`** (opcjonalne, P2) — analogiczne narzędzie tylko-do-odczytu, gated na `role === "master" || role === "admin"` w handlerze — przydatne, gdyby master chciał podejrzeć flotę z poziomu Claude Desktop, nie tylko z przeglądarki. Nie blokuje P0.

## 4. API dla UI: `GET /api/agent-status`

Nowy route `src/app/api/agent-status/route.ts` — sesja NextAuth (nie token API), wzorzec 1:1 z `src/app/api/users/route.ts`:

```ts
const session = await auth();
if (!session?.user) return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
const role = (session.user as { role?: string }).role ?? "member";
if (role !== "master") return NextResponse.json({ error: "Forbidden" }, { status: 403 });
```

Zwraca listę kont z `isBot: true`, każde z aktualnym `AgentStatus` (jeśli istnieje — bot może jeszcze nigdy nic nie wysłać) i ostatnimi ~10 `AgentStatusEvent`, plus policzone `online: boolean` (próg 5 minut od `updatedAt`).

## 5. Strona: `/dashboard/agent-monitoring`

- **`src/app/dashboard/agent-monitoring/page.tsx`** — Server Component, wzorzec 1:1 z `src/app/dashboard/users/page.tsx`: `auth()` → dociągnięcie roli z bazy → `redirect("/dashboard")` jeśli `role !== "master"` → pierwsze pobranie danych bezpośrednio przez Prisma → render `<AgentMonitoringClient initialData={...} />`.
- **`AgentMonitoringClient.tsx`** — client component, odpytuje `/api/agent-status` co ~15 s (ten sam wzorzec `useEffect` + `fetch` co `src/app/dashboard/tasks/CommentsSection.tsx`). Karta na agenta: `BotBadge`, `roleLabel`, kolorowa plakietka statusu (working=zielony, idle=szary, alert=czerwony, offline=czerwony/przekreślony), bieżące zadanie (link do zadania, jeśli `currentTaskId`), pasek koszt dziś/limit, względny czas ostatniego sygnału („2 min temu”), rozwijana historia ostatnich zdarzeń.

## 6. Nawigacja (`src/components/layout/Sidebar.tsx`)

Dokładnie ten sam wzorzec co istniejący, master-only wpis „Użytkownicy”:

```tsx
...(isMaster ? [{ href: "/dashboard/agent-monitoring", label: "Monitorowanie agentów", icon: Activity }] : []),
```

## 7. Dokumentacja i rejestr zmian

- `docs/api-mcp.md` — dopisać `post_agent_status` (i `get_agent_statuses`, jeśli wdrożone) do listy narzędzi + wiersz w tabeli ról.
- `zadania/lista-zmian-aplikacja.md` — nowa pozycja (kolejny numer po #36) po wdrożeniu.

## 8. Pliki do utworzenia/zmiany — podsumowanie

| Plik | Zmiana |
|---|---|
| `prisma/schema.prisma` | + `AgentStatus`, `AgentStatusEvent`, relacja na `User` |
| `src/lib/mcp/agent-status.ts` | nowy — logika zapisu/odczytu |
| `src/lib/mcp/server.ts` | rejestracja `post_agent_status` (+ opcjonalnie `get_agent_statuses`) |
| `src/app/api/agent-status/route.ts` | nowy — GET dla UI, master-only |
| `src/app/dashboard/agent-monitoring/page.tsx` | nowy — Server Component |
| `src/app/dashboard/agent-monitoring/AgentMonitoringClient.tsx` | nowy — polling + karty |
| `src/components/layout/Sidebar.tsx` | + pozycja master-only |
| `docs/api-mcp.md`, `zadania/lista-zmian-aplikacja.md` | aktualizacja dokumentacji |

## 9. Weryfikacja

1. `npx prisma migrate dev --name add-agent-status-monitoring` bez błędów, `npx prisma studio` pokazuje nowe tabele.
2. `npx tsc --noEmit`, `npm run lint` czyste.
3. Ręczny test MCP: token bota „AI - Dev” → wywołanie `post_agent_status` (np. przez `curl` z nagłówkiem `Authorization: Bearer prj_...` albo z poziomu Claude Desktop podłączonego tym tokenem) → sprawdzić wiersz w `prisma studio`.
4. Zalogować się jako `master@local` → `/dashboard/agent-monitoring` pokazuje kartę „AI - Dev” ze statusem z kroku 3; zalogować się jako `member`/bot → strona przekierowuje, link w sidebarze nie istnieje.
5. Test dostępu: użytkownik bez roli master próbujący trafić bezpośrednio pod `/api/agent-status` dostaje 403.

## 10. Kolejność między repozytoriami

1. **Ten plan (Projectly)** — schema + migracja + narzędzie MCP + strona + sidebar. Deploy na Railway.
2. Ręczna weryfikacja tego planu na produkcji (sekcja 9, kroki 3–5) zanim agent Wirtualnego Pracownika zacznie z tego korzystać.
3. Wirtualny Pracownik (drugi plan) — najpierw z flagą `transport: "documentation"` (nic się nie zmienia w zachowaniu), potem przełączenie na `"agent_status_tool"` po potwierdzeniu, że narzędzie MCP odpowiada poprawnie.
4. Po 1–2 tygodniach stabilnej pracy: usunięcie starej gałęzi kodu (dokumentacja-jako-status) po stronie agenta.

## 11. Świadomie poza zakresem

- **Zdalne sterowanie agentem z Projectly** (pauza/stop na żądanie mastera) — zakładka jest read-only; kontrola zostaje lokalna po stronie Wirtualnego Pracownika. Zdalny stop to akcja czerwona i osobna decyzja bezpieczeństwa.
- **`get_agent_statuses` jako narzędzie MCP** — oznaczone jako P2/opcjonalne; nie blokuje P0 (UI czyta bezpośrednio przez `/api/agent-status`).
- **Wielobotowy zespół z `ZESPOL-BOTOW.md`** (Waldek/Krzysztof/Zofia/Zenek/Strateg) — model danych (`roleLabel` per konto) jest już na to gotowy, ale zakładanie kolejnych kont botów to osobna decyzja biznesowa, nie część tego planu.

## 12. Do potwierdzenia przed startem implementacji

1. Próg „offline” w UI — proponuję **5 minut** od `updatedAt`. Zmienić, jeśli cykl publikowania w produkcji będzie inny niż 1–2 min.
2. Czy `post_agent_status` ma być ograniczone wyłącznie do kont `isBot: true`, czy dowolne uwierzytelnione konto może publikować status (np. do testów ręcznych)? Plan zakłada to pierwsze.
3. Limit historii zdarzeń na agenta w `AgentStatusEvent` — proponuję 200 wpisów; do zmiany, jeśli master będzie chciał dłuższą historię w UI.
