# MCP: statusy z detalami zdarzeń i koszty per zadanie

Instrukcja dla agenta AI (drugi agent): jak wysyłać przez MCP **szczegóły zdarzeń** widoczne w monitoringu
oraz **koszt każdego zadania**, żeby master widział rozbicie kosztów per agent. Do przekazania agentowi.

Status: gotowe do wdrożenia (pola dodawane w tej rundzie — patrz sekcja „Wymagane pola").

---

## 1. Szczegóły zdarzeń w historii procesu

Monitoring agenta pokazuje per proces (roleLabel) **historię zdarzeń**. Dziś zdarzenie ma tylko `status` i
krótki `message`. Żeby master mógł „wkliknąć się" w zdarzenie i zobaczyć szczegóły, dochodzi pole **`detail`**.

Narzędzie: **`zbot_post_agent_status`** (bez zmian w sposobie wywołania — jeden wiersz na `roleLabel`, wołaj cyklicznie).

Nowe/istotne pola:
- `message` (istnieje) — krótki komunikat, trafia do historii jako nagłówek zdarzenia.
- `detail` (NOWE, opcjonalne) — dłuższy opis/JSON zdarzenia: co dokładnie się wydarzyło, co przeskanowano,
  wynik kroku, parametry. Pokazywany po rozwinięciu zdarzenia w monitoringu.

Zasada tworzenia zdarzeń: **nowe zdarzenie w historii powstaje, gdy zmienia się `status` ALBO gdy podasz `message`.**
Żeby dołożyć zdarzenie z detalami (np. „przeskanowano 14 zdarzeń"), podaj `message` + `detail`.

Przykład (kacper-monitor melduje wynik skanu):
```json
{
  "roleLabel": "kacper-monitor",
  "status": "working",
  "message": "Przeskanowano 14 zdarzeń",
  "detail": "Źródło: inbox. Nowe: 3, zignorowane: 11. ID: [evt_1, evt_2, evt_3]. Reguła: keyword-match. Czas: 1.2s."
}
```

Dobre praktyki dla `detail`:
- Krótko i konkretnie: liczby, ID, wynik, przyczyna. Może być zwykły tekst lub JSON (string).
- Wysyłaj `detail` przy istotnych krokach (skan, decyzja, błąd), nie przy każdym heartbeacie idle.
- Przy `health: "alert"` opis alertu dawaj w `healthDetail` (to osobne pole nagłówka statusu), a szczegóły
  diagnostyczne w `detail` zdarzenia.

---

## 2. Koszt per zadanie (rozbicie kosztów per agent)

Koszt ma być **indywidualny na agenta** i liczony jako **suma po zadaniach**. Każde zadanie dostaje własny koszt AI.

Narzędzie: **`update_task`** (podajesz tylko pola do zmiany).

Nowe pole:
- `costUsd` (NOWE, opcjonalne, liczba) — koszt AI danego zadania w USD (łączny koszt tokenów/uruchomień na to zadanie).
  Ustawiaj/aktualizuj przy pracy nad zadaniem, a na pewno przy zamknięciu (`status: "done"`).

Przykład (zamknięcie zadania z kosztem):
```json
{
  "taskId": "task_abc123",
  "status": "done",
  "feedback": "Zrobione. Zebrano 3 leady, reszta w podzadaniach.",
  "actualHours": 0.4,
  "costUsd": 0.87
}
```

Jak to jest liczone w aplikacji:
- **Koszt agenta = suma `costUsd` wszystkich jego zadań** (przypisanych do jego konta). Widoczny na pulpicie agenta
  (kafelek „Koszt (zadania)") oraz jako kolumna „Koszt" w tabeli zadań.
- `costTodayUsd` / `costLimitUsd` w `zbot_post_agent_status` zostają jako **dzienny** koszt/limit heartbeatu
  (bieżący stan), niezależnie od sumy per-zadanie. Dwa różne widoki: dzienny (heartbeat) vs skumulowany (zadania).

---

## 3. Podsumowanie: gdzie co wysyłać

| Chcę pokazać | Narzędzie MCP | Pole |
|---|---|---|
| Krótki nagłówek zdarzenia | `zbot_post_agent_status` | `message` |
| Szczegóły zdarzenia (klik → detale) | `zbot_post_agent_status` | `detail` (nowe) |
| Bieżący stan / postęp | `zbot_post_agent_status` | `status`, `progressLabel`, `currentTaskTitle` |
| Koszt dzienny + limit | `zbot_post_agent_status` | `costTodayUsd`, `costLimitUsd` |
| Koszt konkretnego zadania | `update_task` | `costUsd` (nowe) |
| Notatka powykonawcza | `update_task` | `feedback` |
| Rzeczywisty czas | `update_task` | `actualHours` |

Uwaga: pola `detail` (na zdarzeniu statusu) i `costUsd` (na zadaniu) wchodzą do bazy przy najbliższym deployu
(`prisma db push` w `startCommand` Railway). Do tego czasu wysyłanie ich nie zaszkodzi (są opcjonalne), ale
nie będą jeszcze zapisywane.
