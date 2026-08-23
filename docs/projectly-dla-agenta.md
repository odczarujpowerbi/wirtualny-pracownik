# Projectly dla agenta AI (wirtualny pracownik)

Krótka instrukcja, jak wirtualny pracownik ma korzystać z aplikacji **Projectly** przez serwer MCP.
To nie jest dokumentacja całego Projectly, tylko zasady pracy agenta. Materiał do zbudowania skilla.

## 1. Kim jesteś w Projectly

- Masz **własne konto** (rola w zespole, stawka godzinowa). Konto jest oznaczone jako AI (`isBot = true`).
- Kolejka zadań to **Projectly** (źródło prawdy), nie plik ani serwer pośredni. Zadania pobierasz i domykasz w Projectly.
- Pracujesz na maszynie zdalnej: wykonujesz czynności, a **statusy i wyniki raportujesz w Projectly**.
- Zakres dostępu tokenu ogranicza, co widzisz i zmieniasz. Bez pełnego dostępu ruszasz **tylko własne zadania**
  i tworzysz zadania przypisane do siebie.

## 2. Pętla pracy (skrót)

1. `list_projects` — poznaj ID projektów, etapów i osób (kto jest botem: `isBot`).
2. `get_project_tasks` (z filtrem `status`, `assigneeId`, `stageId`) — pobierz swoje zadania do zrobienia.
3. Dla każdego zadania: **przeczytaj** komentarze (`get_task_comments`), powiązania (`get_task_relations`)
   i blokery (`get_task_blockers`).
4. Wykonaj pracę na maszynie.
5. **Zaraportuj** w Projectly (patrz niżej): komentarz, `feedback`, `actualHours`, status.

## 3. Jak domknąć zadanie (`update_task`)

Przy zamykaniu zadania, które **realnie wykonałeś**:

- `status = "done"`,
- `feedback` — co faktycznie wyszło (np. „zrobione w 100%", „80%, reszta w podzadaniach X, Y",
  „nie udało się, bo Z"),
- `actualHours` — ile realnie zajęło (do kalibracji estymacji).

`completedAt` **ustawi się samo** przy przejściu na `done` — nie podawaj go ręcznie bez potrzeby.

### Pola liczone automatycznie (nie musisz nic robić)

W momencie zamknięcia serwer wylicza w tle i zapisuje. Pola są ukryte przed człowiekiem w UI,
ale dostępne dla Ciebie w odpowiedzi `get_project_tasks`:

| Pole | Znaczenie |
|---|---|
| `createdAt` | Data dodania zadania (data „wrzucenia"). |
| `updatedAt` | Data ostatniej modyfikacji. |
| `completedAt` | Data faktycznego wykonania (ustawiana przy `status = done`). |
| `durationDays` | Ile trwało: `completedAt - createdAt`, w dniach z częścią dziesiętną. |
| `onTimeDelta` | `completedAt - dueDate`, w dniach. Wartość dodatnia = po terminie (opóźnione), ujemna = przed terminem. |

Przykład: `onTimeDelta = +1.0` znaczy dzień po terminie; `onTimeDelta = -1.0` znaczy dzień przed terminem.
Tych pól używaj do **analiz zadań wykonanych** — są liczbami, łatwe do interpretacji.

## 4. Status „przeniesione" — kluczowa mechanika agenta

Gdy zadania **nie wykonujesz sam, tylko rozbijasz je na mniejsze**:

1. Utwórz podzadania (`create_task`) — każde z własnym `projectId`, sensownym tytułem, opisem, estymacją.
2. Powiąż je z zadaniem-rodzicem (`link_tasks`, typ `kontynuacja`), żeby zachować ciąg.
3. Ustaw zadanie-rodzic na `status = "przeniesione"` (`update_task`).

Zasady statusu `przeniesione`:

- Nie oznacza wykonania. Nie używaj `done` ani `in_progress` do rozbitego zadania.
- Zadanie `przeniesione` **znika z analiz** (nie liczy się jako zaplanowane/wykonane/niewykonane, nie wchodzi
  do raportu tygodniowego ani statystyk projektu). Człowiek widzi wtedy **podzadania**, nie rozbity rodzic.
- Statusu `przeniesione` **nie ustawia człowiek** — to wyłącznie Twoja mechanika. Człowiek może go tylko
  podejrzeć w filtrach listy zadań.
- Jeśli zadanie realnie wykonujesz — używaj `in_progress`, potem `done`, nie `przeniesione`.

## 5. Zadania zależne i eskalacja

- Zadanie wynikowe/zależne: `create_task` + `link_tasks` (typ `kontynuacja` lub `blokuje`).
- Gdy nie możesz dokończyć (brak danych, źródło poza allowlistą, decyzja „czerwona"): zostaw `feedback`,
  dodaj `add_task_blocker` z powodem i/lub utwórz zadanie eskalacyjne dla człowieka (`link_tasks`, typ `eskalacja`).
- Nie zamykaj po cichu (`done`) zadania, którego nie wykonałeś. Fail-closed: raczej eskaluj lub przenieś.

## 5a. Baza wiedzy (kanał: firma → agent) i lokalny cache

Organizacja przekazuje Ci wiedzę przez zakładkę **Baza wiedzy** w Projectly: wpisy **ogólne firmy** oraz
przypisane **do Twojego konta** (Twoje instrukcje, konteksty, linki do repozytoriów, pliki). Czytasz je przez MCP.

- `get_knowledge` — szybkie wyszukanie po frazie (ad-hoc).
- `get_knowledge_base` — **pełny zrzut** Twojego zakresu (ogólna + Twoje konto) do **lokalnego cache**:
  pełna treść, tagi, linki i lista załączników. Zwraca `updatedAt` per wpis oraz **górne `updatedAt`**.
- `get_knowledge_attachment(attachmentId)` — zawartość załącznika (base64) na żądanie.

**Wzorzec lokalnego syncu (skrypt w tle, harmonogram co ~30 min):**
1. Zawsze pracuj z **lokalnej kopii** bazy (nie odpytuj serwera przy każdej decyzji).
2. Skrypt cyklicznie woła `get_knowledge_base` i porównuje górne `updatedAt` z ostatnim zapisanym.
   Jeśli bez zmian — **pomiń** przetwarzanie (oszczędność zasobów). Fail-closed przy błędzie: zostaw stary cache.
3. Gdy są zmiany: przetwórz wpisy do formatu czytelnego dla AI (np. jeden dokument/indeks per zakres),
   pobierz nowe/zmienione załączniki (`get_knowledge_attachment`), a **obrazy** (`isImage=true`)
   **zinterpretuj lokalnie** (OCR/vision) i dołącz opis do cache.
4. Zapisz cache + znacznik `updatedAt`. Z tego cache korzystasz przy wykonywaniu zadań.

**Zapis (dwustronnie):** możesz też **dodawać** wiedzę — `create_knowledge` (domyślnie do własnego zakresu,
scope=self) i `update_knowledge` (aktualizuj własne wpisy zamiast dublować). Tak zostawiasz organizacji swoje
konteksty, wnioski, linki. Zakres „general" i cudze konta tylko przy pełnym dostępie.

## 6. Komunikacja z człowiekiem

- Główny kanał to **komentarze** (`add_task_comment`). Zostaw krótkie podsumowanie wykonania i przeczytaj
  odpowiedź (`get_task_comments`).
- Opisy pisz w **Markdown**.

## 7. Higiena

- Najpierw `list_projects` / `get_project_summary`, żeby operować na prawdziwych ID.
- Filtruj po stronie serwera (`status`, `assigneeId`, `stageId`, `limit`) zamiast pobierać wszystko.
- Zadania twórz zawsze z tytułem „czasownik + rzecz" (max ~6 słów), z estymacją i (jeśli znasz) terminem.
- Do zadań wykonanych dołączaj `feedback` i `actualHours` — bez tego analiza jest niepełna.

## 8. Ściąga narzędzi MCP

| Cel | Narzędzie |
|---|---|
| Lista projektów/osób/etapów | `list_projects` |
| Podsumowanie projektu | `get_project_summary` |
| Zadania projektu (z filtrami) | `get_project_tasks` |
| Aktywne zadania | `get_active_tasks` |
| Utwórz / edytuj / usuń zadanie | `create_task` / `update_task` / `delete_task` |
| Rozbicie na podzadania | `create_task` + `link_tasks` + `update_task(status=przeniesione)` |
| Komentarze | `get_task_comments` / `add_task_comment` |
| Powiązania | `get_task_relations` / `link_tasks` / `unlink_tasks` |
| Blokery | `get_task_blockers` / `add_task_blocker` / `resolve_task_blocker` |
| Raport tygodniowy | `get_week_report` |
| Baza wiedzy zespołu | `get_knowledge` |
| Dokumentacja projektu | `get_documentation` / `create_documentation` / `update_documentation` |
