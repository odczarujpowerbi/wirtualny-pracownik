"""
Autonomiczny "naprawiacz repozytorium" — stoi OBOK głównej pętli zadań (nie w
procesie runner_loop.py, jak kacper_monitor.py). Wyzwalany cyklicznie z
job_scheduler.py: skanuje ZAKOŃCZONE zadania (state_store event "block_closed")
i dla tych z KONKRETNYM sygnałem problemu — eskalacja do człowieka, bramka
jakości odrzuciła, podwójne wykonanie (runner_loop.DUPLICATE_GUARD_MINUTES) —
uruchamia prawdziwego subagenta Claude Code z dostępem do CAŁEGO repo (nie do
jednego folderu zadania jak agentic_worker.py), żeby zaproponował konkretną
poprawkę kodu albo brakującą umiejętność (.claude/skills/).

Status "done" jest ODRZUCANY Z ZASADY (decyzja właściciela 25.08.2026) —
NAWET gdy w historii był falstart (bramka odrzuciła, potem przeszła po
poprawce) — zadanie już jest wykonane, użytkownik nie chce, żeby bot
"weryfikował" coś, co już się skończyło. Sygnał liczy się tylko wtedy, gdy
status końcowy WCIĄŻ nie jest rozwiązany (dziś: "needs_approval").

Decyzja właściciela 25.08.2026 (po incydencie: zadanie "analiza nowych osób w
MailerLite" dostało zestawienie kampanii — zły routing narzędzia, którego nic
w pipeline'ie nie złapało):

Zasady bezpieczeństwa:
  - Subagent NIE dostaje bezpośredniego dostępu do prawdziwego katalogu repo
    ani do poleceń git/gh — pracuje WYŁĄCZNIE w tymczasowym `git worktree`
    (Read/Write/Edit tam), a commit/push/PR robi TEN skrypt (Python) PO tym,
    jak subagent skończy — subagent nigdy sam nie woła gita.
  - ZAWSZE nowy branch + próba PR (`gh pr create`) — NIGDY commit na
    main/master, NIGDY auto-merge, NIGDY force-push. Brak `gh` na maszynie =
    branch zostaje wypchnięty na origin, PR trzeba otworzyć ręcznie (fail-soft,
    nie blokuje — patrz _otworz_pr).
  - Domyślnie WYŁĄCZONY w schedule.yaml (jak każdy job tworzący/zmieniający
    coś trwałego) — włącz świadomie po przejrzeniu pierwszych przebiegów.
  - Rate-limit: co najwyżej `limit` zadań na przebieg (domyślnie 1) — reszta
    poczeka na kolejny cykl, żeby nie zalać repo dziesiątkami równoległych
    branchy naraz. Każde task_id sprawdzane co najwyżej raz (kursor +
    `reviewed` w runs/repo_improver_state.json, wzorzec kacper_monitor.py).
"""

import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import model_registry
import projectly_client
import state_store
import task_thinker

APP_DIR = Path(__file__).parent
REPO_DIR = APP_DIR.parent
STATE_PATH = APP_DIR / "runs" / "repo_improver_state.json"
BASE_BRANCH = "main"
SUBAGENT_TIMEOUT_SECONDS = 900
RESULT_FILENAME = "AUTO_FIX_SUMMARY.md"
# Rozszerzenia plików wyniku, których treść da się dołożyć do promptu wprost
# (tekst). Dla innych (.pdf/.docx/.xlsx) odnotowujemy tylko nazwę — bez nowej
# zależności do parsowania, której dziś nie ma w requirements.txt.
_ROZSZERZENIA_TEKSTOWE = (".md", ".txt")
# Ile razy ponowić naprawę zadania, które padło z powodu awarii NARZĘDZIA
# (akcja="brak_akcji"), zanim uznamy to za permanentne i przestaniemy próbować
# (np. subagent trwale niedostępny) — nie chcemy zapętlić się w nieskończoność
# na jednym uporczywie zawodzącym task_id.
MAX_PROB_BRAK_AKCJI = 3


def _load_state(path=STATE_PATH):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # Jak kacper_monitor.py: pierwsze włączenie startuje od BIEŻĄCEGO max id,
    # nie od zera — inaczej pierwszy przebieg przeglądałby retroaktywnie całą
    # historię zadań.
    return {"last_event_id": state_store.max_event_id(), "reviewed": {}}


def _save_state(state, path=STATE_PATH):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _historia_zdarzen(task_id):
    conn = state_store.get_connection()
    rows = conn.execute(
        "SELECT event_type, decision, detail, reason FROM events WHERE task_id=? ORDER BY id",
        (task_id,),
    ).fetchall()
    conn.close()
    return rows


def _historia_tekst(rows, limit=15):
    linie = []
    for event_type, decision, detail, reason in rows[-limit:]:
        tresc = (reason or detail or "").strip()
        if not tresc:
            continue
        znacznik = event_type + (f"={decision}" if decision else "")
        linie.append(f"- {znacznik}: {tresc[:300]}")
    return "\n".join(linie) or "(brak szczegółów w dzienniku zdarzeń)"


def sygnal_problemu(task_id):
    """Zwraca (powod, historia_tekstem) gdy zadanie ma konkretny sygnał
    problemu warty przejrzenia repo, albo (None, None) gdy zakończyło się
    czysto — fail-closed w stronę NIE reagowania (brak sygnału = spokój).

    Status "done" jest ODRZUCANY z zasady (decyzja właściciela 25.08.2026),
    NAWET jeśli w historii był falstart (np. bramka odrzuciła, ale potem
    przeszła po poprawka_materialu.py) — zadanie już jest wykonane, nie ma
    czego przeglądać. Sygnał liczy się TYLKO gdy końcowy status wciąż nie
    jest rozwiązany (dziś: "needs_approval")."""
    task = state_store.get_task(task_id)
    if task is None or task["status"] == "done":
        return None, None
    rows = _historia_zdarzen(task_id)
    historia = _historia_tekst(rows)

    if task["status"] == "needs_approval":
        return "eskalacja_do_czlowieka", historia
    for event_type, decision, _detail, _reason in rows:
        if event_type == "duplicate_skip":
            return "podwojne_wykonanie", historia
        if event_type == "quality_gate" and decision == "gate_failed":
            return "bramka_odrzucila", historia
    return None, None


def _nazwa_brancha(task_id):
    slug = re.sub(r"[^a-z0-9]+", "-", task_id.lower()).strip("-") or "zadanie"
    znacznik = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"auto-fix/{slug}-{znacznik}"


def _run(cmd, cwd=None, timeout=60, check=False, env=None):
    """Jedyne miejsce wołające subprocess.run dla operacji git/gh/claude — testy
    dymne podmieniają TĘ funkcję jedną atrapą zamiast łatać każde wywołanie
    osobno. `env=None` -> dziedziczy środowisko procesu (git/gh); subagent
    Claude Code dostaje env JAWNIE, patrz _uruchom_subagenta."""
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout, check=check, env=env)


def _przygotuj_worktree(branch):
    _run(["git", "-C", str(REPO_DIR), "fetch", "origin", BASE_BRANCH], timeout=120, check=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="repo-auto-fix-"))
    _run(["git", "-C", str(REPO_DIR), "worktree", "add", "-b", branch, str(tmp_dir),
          f"origin/{BASE_BRANCH}"], timeout=60, check=True)
    return tmp_dir


def _posprzataj_worktree(worktree, branch):
    _run(["git", "-C", str(REPO_DIR), "worktree", "remove", "--force", str(worktree)], timeout=60)
    _run(["git", "-C", str(REPO_DIR), "branch", "-D", branch], timeout=60)


def _plik_wyniku_tekst(task):
    """Treść realnego pliku wyniku zadania z OneDrive (dowód, nie tylko log
    zdarzeń) — ten sam folder, który zapisuje runner_loop._save_result_to_onedrive.

    Przyjmuje CAŁE zadanie (nie sam task_id): podzadanie (task["parent_task_id"]
    ustawione) NIE dostaje własnego folderu — runner_loop._save_result_to_onedrive
    zapisuje jego wynik do folderu RODZICA (effective_id = parent_task_id or
    task_id, patrz runner_loop.py). Żywy bug 26.08.2026, znaleziony w audycie
    27.08.2026: szukanie po WŁASNYM task_id podzadania zawsze cicho zwracało ''
    (fail-soft bez wyjątku) — subagent naprawiający kod nigdy nie widział
    realnej treści wyniku dla flagowanych podzadań, tylko log zdarzeń.

    Pliki .md/.txt wchodzą wprost, dla .pdf/.docx/.xlsx odnotowujemy tylko nazwę
    (bez nowej zależności do parsowania). Fail-soft: brak ONEDRIVE_TASKS_ROOT/
    folderu/błąd -> ""."""
    root = os.environ.get("ONEDRIVE_TASKS_ROOT")
    if not root:
        return ""
    effective_id = task.get("parent_task_id") or task.get("task_id")
    try:
        foldery = sorted(Path(root).glob(f"{effective_id}_*"))
        if not foldery:
            return ""
        czesci = []
        for plik in sorted(foldery[0].iterdir()):
            if not plik.is_file():
                continue
            if plik.suffix.lower() in _ROZSZERZENIA_TEKSTOWE:
                czesci.append(f"--- {plik.name} ---\n{plik.read_text(encoding='utf-8').strip()}")
            else:
                czesci.append(f"--- {plik.name} (binarny, nie odczytany) ---")
        return "\n\n".join(czesci)
    except OSError:
        return ""


def _zbuduj_prompt(task, powod, historia, plik_wyniku=""):
    sekcja_pliku = (
        f"\n\nPlik wyniku zadania (dowód, nie tylko log zdarzeń):\n{plik_wyniku}"
        if plik_wyniku else ""
    )
    return (
        "Jesteś agentem naprawiającym repozytorium 'wirtualny-pracownik' (Python, "
        "pipeline agenta AI). Poniższe PRAWDZIWE zadanie zakończyło się sygnałem "
        "problemu — przeanalizuj kod w TYM katalogu (Twój własny worktree, wolno "
        "Ci czytać/edytować cokolwiek tutaj) i albo (a) napraw KONKRETNY błąd w "
        "kodzie, który to spowodował, albo (b) jeśli brakuje realnej zdolności "
        "(np. narzędzia dla konkretnej domeny), dodaj ją. Jeśli po analizie "
        "uznasz, że w kodzie nie ma nic do poprawienia (np. to był jednorazowy "
        "problem po stronie zewnętrznego API/danych) — NIE zmieniaj żadnych "
        "plików i zakończ bez edycji. WOLNO Ci wyłącznie MODYFIKOWAĆ/EDYTOWAĆ "
        "istniejące pliki i DODAWAĆ nowe — NIGDY nie usuwaj żadnego pliku "
        "(decyzja właściciela repozytorium).\n\n"
        f"Sygnał problemu: {powod}\n"
        f"Zadanie: {task.get('title', '')}\n"
        f"Cel: {task.get('expected_result', '')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria', '')}\n\n"
        f"Co się stało (dziennik zdarzeń tego zadania):\n{historia}"
        f"{sekcja_pliku}\n\n"
        f"Jeśli wprowadzisz zmiany, zapisz w pliku '{RESULT_FILENAME}' w katalogu "
        "głównym KRÓTKIE podsumowanie (co, dlaczego, jak to zweryfikować) — to "
        "trafi jako opis Pull Requesta."
    )


def _uruchom_subagenta(worktree, prompt):
    claude_exe = task_thinker._find_claude()
    if not claude_exe:
        return {"executed": False, "powod": "Brak Claude Code (claude login) na tej maszynie."}
    _, model = model_registry.resolve("repo_auto_improver.napraw_zadanie")
    # ANTHROPIC_API_KEY usuwany ze środowiska podprocesu z tego samego powodu co
    # w agentic_worker.py/task_thinker._think_via_claude_code: obecność klucza
    # wyłącza connectory `claude login`, `claude -p` kończy się błędem "claude.ai
    # connectors are disabled...". Żywy bug 25-26.08.2026: repo_auto_improver
    # NIGDY nie wykonał realnej naprawy od chwili włączenia — każde ze 129+
    # uruchomień kończyło się dokładnie tym błędem, bo ta poprawka (już dawno
    # zrobiona w agentic_worker.py) nie została tu zastosowana.
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    try:
        result = _run(
            # Prompt zaraz po --model, PRZED --allowedTools/--add-dir (te dwa są
            # wariadyczne — konsumują każdy kolejny token bez "-" na początku,
            # patrz agentic_worker.py dla tego samego wzorca/incydentu).
            [claude_exe, "-p", "--model", model, prompt, "--permission-mode", "acceptEdits",
             "--allowedTools", "Read Write Edit Skill", "--add-dir", str(worktree)],
            cwd=worktree, timeout=SUBAGENT_TIMEOUT_SECONDS, env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"executed": False, "powod": f"Subagent nie powiódł się: {exc}"}
    if result.returncode != 0:
        # stderr I stdout — niektóre błędy Claude Code CLI (np. komunikaty
        # połączenia/uprawnień) trafiają na stdout, nie stderr. Żywy bug
        # 27.08.2026, znaleziony przy diagnozowaniu KOLEJNEGO błędu po naprawie
        # ANTHROPIC_API_KEY: komunikat błędu był pusty (tylko stderr sprawdzany),
        # więc niemożliwe było zdiagnozować, co faktycznie poszło nie tak.
        tresc_bledu = (result.stderr or "").strip() or (result.stdout or "").strip()
        return {"executed": False,
                "powod": f"Subagent zwrócił kod {result.returncode}: {tresc_bledu[:300]}"}
    return {"executed": True}


def _ma_zmiany(worktree):
    result = _run(["git", "-C", str(worktree), "status", "--porcelain"], timeout=30)
    return bool((result.stdout or "").strip())


def _commituj_i_wypchnij(worktree, branch, opis):
    _run(["git", "-C", str(worktree), "add", "-A"], timeout=60, check=True)
    _run(["git", "-C", str(worktree), "commit", "-m", opis], timeout=60, check=True)
    push = _run(["git", "-C", str(worktree), "push", "-u", "origin", branch], timeout=120)
    return push.returncode == 0, (push.stderr or "").strip()[:400]


def _otworz_pr(branch, tytul, opis):
    if not shutil.which("gh"):
        return {"utworzono": False, "powod": "Brak `gh` CLI na tej maszynie — otwórz PR ręcznie z brancha."}
    result = _run(["gh", "pr", "create", "--base", BASE_BRANCH, "--head", branch,
                   "--title", tytul, "--body", opis], cwd=REPO_DIR, timeout=60)
    if result.returncode != 0:
        return {"utworzono": False, "powod": (result.stderr or "").strip()[:400]}
    return {"utworzono": True, "url": (result.stdout or "").strip()}


def _opis_akcji_dla_czlowieka(wynik):
    akcja = wynik.get("akcja")
    if akcja == "pr_utworzony":
        return f"Utworzono Pull Request: {wynik.get('url', '?')}"
    if akcja == "branch_bez_pr":
        return f"Branch wypchnięty ({wynik.get('branch', '?')}), ale PR NIE otwarty: {wynik.get('powod', '?')}"
    if akcja == "commit_nieudany":
        return f"Commit/push nie powiódł się: {wynik.get('powod', '?')}"
    if akcja == "brak_zmian":
        return "Przeanalizowano kod, ale nie znaleziono nic do poprawienia."
    if akcja == "brak_akcji":
        return f"Nie udało się uruchomić naprawy: {wynik.get('powod', '?')}"
    return f"Nieznana akcja: {akcja}"


def _zaloguj_wynik(client, task_id, wynik):
    """Zapisuje, co repo_auto_improver zrobił dla tego zadania — komentarz na
    zadaniu ŹRÓDŁOWYM w Projectly (kanał, który właściciel już obserwuje), nie
    tylko wpis w runs/repo_improver_state.json. Decyzja właściciela 26.08.2026:
    bez tego nie było żadnej widocznej informacji o działaniu agenta poza
    stanem lokalnym na dysku. Fail-soft: brak klienta/błąd zapisu komentarza
    NIE MOŻE ubić cyklu naprawy — to dodatkowy ślad, nie krytyczny krok."""
    if client is None:
        return
    tresc = f"🔧 repo_auto_improver: {_opis_akcji_dla_czlowieka(wynik)}"
    try:
        client.post_comment(task_id, tresc)
    except Exception as exc:  # noqa: BLE001
        print(f"[repo_auto_improver] Nie udało się zapisać komentarza z logiem: {exc}")


def napraw_zadanie(task_id, powod, historia):
    """Pełny cykl: worktree -> subagent -> commit/push -> PR. Zwraca
    {"task_id", "akcja", ...} — akcja jedna z: brak_akcji (subagent
    niedostępny/zawiódł), brak_zmian (nic do poprawy), commit_nieudany,
    branch_bez_pr (brak `gh`), pr_utworzony. Nigdy nie rzuca — każda awaria
    degraduje do wpisu z powodem, zamiast wywalać cały cykl."""
    task = state_store.get_task(task_id)["payload"]
    branch = _nazwa_brancha(task_id)
    worktree = None
    try:
        worktree = _przygotuj_worktree(branch)
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
        return {"task_id": task_id, "akcja": "brak_akcji", "powod": f"Przygotowanie worktree nie powiodło się: {exc}"}

    try:
        plik_wyniku = _plik_wyniku_tekst(task)
        wynik_subagenta = _uruchom_subagenta(worktree, _zbuduj_prompt(task, powod, historia, plik_wyniku))
        if not wynik_subagenta["executed"]:
            return {"task_id": task_id, "akcja": "brak_akcji", "powod": wynik_subagenta["powod"]}

        if not _ma_zmiany(worktree):
            return {"task_id": task_id, "akcja": "brak_zmian",
                    "powod": "Subagent nie znalazł nic do poprawy w kodzie."}

        podsumowanie_path = worktree / RESULT_FILENAME
        podsumowanie = (podsumowanie_path.read_text(encoding="utf-8").strip()
                        if podsumowanie_path.exists() else "(subagent nie zostawił podsumowania)")

        ok, blad = _commituj_i_wypchnij(worktree, branch, f"auto-fix: {task.get('title', '')[:60]} ({powod})")
        if not ok:
            return {"task_id": task_id, "akcja": "commit_nieudany", "powod": blad}

        pr = _otworz_pr(branch, f"[auto-fix] {task.get('title', '')[:60]}", podsumowanie)
        return {"task_id": task_id, "branch": branch,
                "akcja": "pr_utworzony" if pr.get("utworzono") else "branch_bez_pr", **pr}
    finally:
        _posprzataj_worktree(worktree, branch)


def run_repo_improvement_cycle(state_path=STATE_PATH, limit=1, client=None):
    """Dwa niezależne kroki, żeby rate-limit (`limit` na przebieg) nigdy nie
    gubił zadania: (1) WYKRYWANIE — kursor po evencie 'block_closed' zawsze
    idzie do przodu, każde nowe zadanie trafia do reviewed (brak sygnału) albo
    do trwałej kolejki `kolejka` (sygnał jest, jeszcze nie naprawione);
    (2) NAPRAWA — zdejmuje z `kolejka` co najwyżej `limit` zadań, kolejka
    persystuje w stanie między przebiegami, więc nic rate-limitowane nie ginie.

    `client`: opcjonalny ProjectlyClient — do zapisania komentarza z logiem
    działania na zadaniu źródłowym (_zaloguj_wynik). Brak podania -> próba
    projectly_client.get_client(), fail-soft do None (bez klienta logowanie
    po prostu jest pomijane, cykl naprawy działa dalej)."""
    if client is None:
        try:
            client = projectly_client.get_client()
        except Exception:  # noqa: BLE001 — logowanie jest dodatkiem, nie warunkiem naprawy
            client = None
    state = _load_state(state_path)
    events = state_store.get_events_since(state.get("last_event_id", 0))
    zamkniete = [e for e in events if e["event_type"] == "block_closed"]
    new_last_id = events[-1]["id"] if events else state.get("last_event_id", 0)
    reviewed = state.setdefault("reviewed", {})
    kolejka = state.setdefault("kolejka", [])

    for event in zamkniete:
        task_id = event["task_id"]
        if task_id in reviewed or task_id in kolejka:
            continue
        powod, _historia = sygnal_problemu(task_id)
        if powod:
            kolejka.append(task_id)
        else:
            reviewed[task_id] = "brak_sygnalu"
    state["last_event_id"] = new_last_id

    retry_counts = state.setdefault("retry_counts", {})
    naprawiono = []
    while kolejka and len(naprawiono) < limit:
        task_id = kolejka.pop(0)
        powod, historia = sygnal_problemu(task_id)
        if not powod:
            reviewed[task_id] = "brak_sygnalu"
            retry_counts.pop(task_id, None)
            continue
        wynik = napraw_zadanie(task_id, powod, historia)
        _zaloguj_wynik(client, task_id, wynik)
        naprawiono.append(wynik)

        if wynik.get("akcja") == "brak_akcji":
            # Awaria NARZĘDZIA (np. subagent chwilowo niedostępny), nie decyzja
            # "nic do naprawy" — kwalifikuje się do ponownej próby, nie
            # permanentnego zablokowania. Żywy bug 25-26.08.2026 (znaleziony w
            # audycie 27.08.2026): 142 zadania padły przez brak usunięcia
            # ANTHROPIC_API_KEY ze środowiska subprocesu i ŻADNE z nich nigdy
            # nie zostałoby ponowione, mimo że bug został naprawiony — bo
            # "brak_akcji" trafiał do `reviewed` na równi z "brak_zmian"
            # (subagent faktycznie uznał, że nie ma czego poprawiać).
            proby = retry_counts.get(task_id, 0) + 1
            retry_counts[task_id] = proby
            if proby < MAX_PROB_BRAK_AKCJI:
                kolejka.append(task_id)
            else:
                reviewed[task_id] = wynik.get("akcja", "?")
                del retry_counts[task_id]
        else:
            reviewed[task_id] = wynik.get("akcja", "?")
            retry_counts.pop(task_id, None)

    _save_state(state, state_path)
    return {"events_scanned": len(events), "naprawiono": naprawiono, "w_kolejce": len(kolejka)}


if __name__ == "__main__":
    print(run_repo_improvement_cycle())
