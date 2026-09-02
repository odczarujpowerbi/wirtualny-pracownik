"""
Budowa promptu dla subagenta (agentic_worker.py). Wydzielone z agentic_worker.py
02.09.2026, bo tamten plik przekroczył 300 linii (limit z coding-rules.md), a
budowa promptu to osobna odpowiedzialność niż uruchomienie i rozliczenie
subagenta: tu decydujemy, CO subagent wie, tam, JAK go odpalamy.

Prompt składa się z bloków, każdy fail-soft (błąd/brak danych pomija TEN blok,
nie blokuje wykonania zadania):
  1. kontekst firmy (kontekst_firmy.zbuduj, ta sama funkcja co w task_brief_builder),
  2. nazwa projektu z Projectly (client.project_name),
  3. projekt/etap i digest wiedzy z kesza (context_cache.context_block),
  4. rodzeństwo podzadań (task["sibling_tasks"], ustawiane przez runner_loop),
  5. STANDARDY z .claude/rules (zasady_pracy.blok), nowe 02.09.2026,
  6. treść zadania z planem,
  7. instrukcja wykonania: w piaskownicy repozytorium ALBO w folderze zadania.

Blok standardów jest tym, czego subagentowi brakowało najbardziej: pracował bez
konwencji commitów, bez limitów rozmiaru plików, bez standardu Power BI, bo
nikt mu ich nie podał (`.claude/rules` czyta Claude Code interaktywnie, nie
proces headless startujący w pustym folderze zadania).
"""

import context_cache
import kontekst_firmy
import zasady_pracy

RESULT_FILENAME = "wynik.md"
OPIS_COMMITA_FILENAME = "opis-commita.txt"


def _kontekst_firmy_blok(task):
    """Fail-soft: błąd/brak dopasowania -> pusty string, nie blokuje promptu."""
    tekst_zadania = " ".join(str(task.get(k) or "") for k in ("title", "description"))
    try:
        return kontekst_firmy.zbuduj(tekst_zadania)
    except Exception:  # noqa: BLE001: kontekst jest dodatkiem, nie warunkiem wykonania
        return ""


def _kontekst_kesza_blok(task, context):
    """Projekt+etap i digest bazy wiedzy z context_cache.py (decyzja właściciela
    30.08.2026). context=None (kesz nieodświeżony/brak klienta w tym wywołaniu)
    -> pusty string, fail-soft."""
    if not context:
        return ""
    return context_cache.context_block(context, task)


def _kontekst_projektu_blok(task, client):
    """Fail-soft: brak client/project_id albo błąd -> pusty string."""
    if client is None or not task.get("project_id"):
        return ""
    try:
        nazwa = client.project_name(task["project_id"])
    except Exception:  # noqa: BLE001
        return ""
    return f"Projekt: {nazwa}" if nazwa else ""


def _kontekst_rodzenstwa_blok(task):
    """Inne podzadania tego samego zadania głównego, ustawiane przez
    runner_loop.py w task["sibling_tasks"]. Fail-soft: brak/puste -> ''."""
    rodzenstwo = task.get("sibling_tasks") or []
    if not rodzenstwo:
        return ""
    linie = "\n".join(
        f"- {s.get('title') or '?'} (status: {s.get('status') or '?'})" for s in rodzenstwo
    )
    return f"Inne podzadania tego samego zadania głównego:\n{linie}"


def _zasady_blok(task, sandbox):
    """Standardy z .claude/rules. Fail-soft, jak każdy inny blok kontekstu."""
    try:
        return zasady_pracy.blok(task, praca_w_repo=bool(sandbox and sandbox.get("ok")))
    except Exception:  # noqa: BLE001
        return ""


def _instrukcja_repo(sandbox, folder):
    """Instrukcja wykonania dla zadania w repozytorium.

    Gita NIE zostawiamy modelowi: commit/push/PR robi repo_publish.py po
    zakończeniu pracy, żeby numeracja commitów ("NN - opis") była policzona z
    historii repo, a nie zgadnięta. Model dostarcza tylko OPIS commitu, bo tylko
    on wie, co faktycznie zrobił."""
    return (
        f"Pracujesz w prawdziwym repozytorium git: {sandbox['path']}\n"
        f"Jesteś już na branchu zadania '{sandbox['branch']}' (gałąź bazowa: "
        f"{sandbox['base_branch']}). To Twoja własna kopia repozytorium, nikomu jej "
        "nie zabierasz.\n\n"
        "Wykonaj zadanie NAPRAWDĘ w tym repozytorium: czytaj kod, wprowadzaj zmiany w "
        "plikach, dodawaj nowe pliki, uruchamiaj to, co potrzebne (testy, budowanie, "
        "skrypty) przez Bash. Jeśli repozytorium ma testy albo bramkę jakości, URUCHOM "
        "je przed zakończeniem i napisz w wyniku, co pokazały.\n\n"
        "Zasady pracy z gitem w tym trybie:\n"
        "- NIE wołaj `git commit`, `git push` ani `git merge`. Commit wg konwencji "
        "firmowej, push brancha i pull request robi system po Tobie.\n"
        "- `git status`, `git diff`, `git log` możesz wołać do woli, to Twój wgląd w stan.\n"
        "- NIGDY nie usuwaj żadnego pliku (decyzja właściciela repozytorium) i nigdy nie "
        "zapisuj w repozytorium sekretów, kluczy ani plików .env.\n\n"
        f"Na koniec zapisz DWA pliki w folderze zadania ({folder}):\n"
        f"- '{RESULT_FILENAME}' (Markdown): pełne, czytelne dla człowieka rozwiązanie "
        "zadania wraz z opisem, co zmieniłeś w repozytorium i z jakim wynikiem testów. "
        "To ma być PEŁNE ROZWIĄZANIE, nie opis planu ani streszczenie zamiarów.\n"
        f"- '{OPIS_COMMITA_FILENAME}': JEDNA linia, po polsku, zwięźle co zostało zrobione "
        "(bez numeru, numer doda system). Przykład: 'dodano walidację formularza kontaktu'."
    )


def _instrukcja_folder_zadania():
    """Instrukcja jak dotąd: praca w pustym folderze zadania, bez repozytorium."""
    return (
        "Wykonaj to zadanie NAPRAWDĘ w bieżącym katalogu, czytaj/pisz pliki, "
        "szukaj i czytaj strony w internecie gdy to pomaga (masz do tego "
        "narzędzia), uruchamiaj co potrzebne do realizacji planu. Finalną, "
        f"czytelną dla człowieka odpowiedź zapisz w pliku '{RESULT_FILENAME}' "
        "(Markdown) w bieżącym katalogu, to ma być PEŁNE ROZWIĄZANIE zadania, "
        "nie opis planu ani streszczenie tego, co zamierzasz zrobić. WOLNO Ci "
        "wyłącznie MODYFIKOWAĆ/EDYTOWAĆ istniejące pliki i DODAWAĆ nowe, "
        "NIGDY nie usuwaj żadnego pliku (decyzja właściciela repozytorium). "
        "W tym trybie NIE wołaj git (commit/push/branch): bieżący katalog leży "
        "wewnątrz repozytorium wirtualnego pracownika, więc commit zapisałby "
        "zmiany w cudzym repozytorium. Zadanie dotyczące repozytorium dostaje "
        "własną piaskownicę i osobne instrukcje."
    )


def build(task, plan_text, folder, client=None, sharepoint_folder=None,
          context=None, sandbox=None):
    """Pełny prompt subagenta. `sandbox` to wynik repo_workspace.przygotuj()
    (None, gdy zadanie nie dotyczy repozytorium)."""
    bloki_kontekstu = [
        blok for blok in (
            _kontekst_firmy_blok(task),
            _kontekst_projektu_blok(task, client),
            _kontekst_kesza_blok(task, context),
            _kontekst_rodzenstwa_blok(task),
            _zasady_blok(task, sandbox),
        )
        if blok
    ]
    kontekst = ("\n\n".join(bloki_kontekstu) + "\n\n") if bloki_kontekstu else ""
    praca_w_repo = bool(sandbox and sandbox.get("ok"))
    sharepoint_akapit = (
        f"\n\nMasz TAKŻE zapis do folderu '{sharepoint_folder}' (ten sam folder zadania na "
        "SharePoint/OneDrive, do którego trafi finalny wynik). Jeśli zadanie wymaga "
        "dostarczenia realnego pliku (np. arkusz, dokument, zestawienie), zapisz go TAM "
        "wprost, oprócz opisu w wyniku.md."
        if sharepoint_folder else ""
    )
    return (
        kontekst +
        f"Zadanie: {task.get('title', '')}\n"
        f"Cel: {task.get('expected_result', '')}\n"
        f"Kryteria akceptacji: {task.get('acceptance_criteria', '')}\n"
        f"Opis: {(task.get('description') or '')[:2000]}\n\n"
        f"Zatwierdzony plan podejścia:\n{plan_text}\n\n"
        + (_instrukcja_repo(sandbox, folder) if praca_w_repo else _instrukcja_folder_zadania())
        + sharepoint_akapit
    )
