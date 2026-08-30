"""
Sterowanie botem Z POZIOMU PROJECTLY (decyzja właściciela 29.08.2026) — jedno
STAŁE zadanie per ROLA ("🎛️ Kontrola bota: <rola>"), którego STATUS steruje
lokalną pauzą (control.py, ten sam mechanizm co przycisk Pauza/Wznów w
dashboard.py).

PRIORYTETOWO: job_scheduler.py wywołuje sync() na SAMYM POCZĄTKU każdego
ticku pętli — PRZED sprawdzeniem, czy odpalić jakikolwiek inny job (patrz
run_scheduler()). To gwarantuje, że zmiana statusu w Projectly działa od
razu na następnym ticku (domyślnie co 2s), zanim bot zdąży spojrzeć na
cokolwiek innego — nie jest to jeszcze jeden zwykły job w harmonogramie.

Mapowanie statusu (świadomie asymetryczne):
    status == "done"        -> bot WSTRZYMANY (control.pause())
    KAŻDY inny status       -> bot pracuje normalnie (control.resume(),
                               TYLKO jeśli to WŁAŚNIE ten mechanizm go wstrzymał)
Domyślny status nowo utworzonego zadania w Projectly to "todo" — gdyby "todo"
oznaczało pauzę, bot zatrzymywałby się sam automatycznie zaraz po utworzeniu
własnego zadania kontrolnego. "done" jako pauza unika tego, i jest intuicyjne
("zamykam = wyłączam").

Współdzielenie z panelem operatora (dashboard.py): resume() jest wołane TYLKO
gdy aktualny powód pauzy to marker TEGO modułu (patrz `_pause_reason`) — więc
ręczna pauza z dashboardu (inny tekst powodu) NIE zostanie cicho cofnięta
przez ten mechanizm, dopóki ktoś nie ustawi z powrotem statusu zadania na
"done" i potem z powrotem na coś innego. Odwrotnie: jeśli bot jest już
wstrzymany (z dowolnego powodu) i status w Projectly to "done", nic nie
robimy — nie nadpisujemy istniejącego powodu pauzy.

Fail-soft: błąd sieci/Projectly NIE zmienia bieżącego stanu pauzy (ani nie
wstrzymuje, ani nie wznawia) — chwilowa niedostępność Projectly nie może
zrobić bota kruchym. Throttlowane do POLL_SECONDS między REALNYMI
zapytaniami do Projectly (job_scheduler.py woła sync() na każdym ticku, 2s
domyślnie — bez throttlingu zalewałoby to Projectly zapytaniami co 2s).
"""

import json
import time
from pathlib import Path

import control
import env_bootstrap
from projectly_client import get_client

POLL_SECONDS = 15

CONTROL_DESCRIPTION = (
    "Zadanie sterujące tym botem z poziomu Projectly (dodane 29.08.2026, decyzja "
    "właściciela). Status 'Done' = bot WSTRZYMANY — nie podejmuje nowej pracy, "
    "aktualne zadanie kończy się samo. Każdy inny status (todo/in_progress) = "
    "bot pracuje normalnie. Sprawdzane priorytetowo na początku każdego cyklu "
    "schedulera — przed jakimkolwiek innym zadaniem."
)

# Throttling w pamięci procesu (nie w pliku) — każdy proces (dev/checker/
# marketing) ma własny import tego modułu, więc osobny stan throttlingu i tak.
_last_checked_at = None


def _control_task_title(role):
    return f"🎛️ Kontrola bota: {role}"


def _pause_reason(role):
    return f"Wstrzymany z Projectly (zadanie kontrolne '{_control_task_title(role)}')."


def _state_path_for_role(role):
    suffix = "" if role == "dev" else f"_{role}"
    return Path(__file__).parent / "runs" / f"remote_control_state{suffix}.json"


def _load_state(path):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    return {}


def _save_state(state, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_or_create_control_task(client, role, state, admin_project_id):
    """Cache po task_id w stanie lokalnym (jedno zapytanie mniej na sync po
    pierwszym udanym uruchomieniu) — ale sam STATUS i tak zawsze czytamy na
    żywo (_task_status), cache dotyczy tylko ID, nie stanu.

    list_tasks(project_id=...) świadomie bez filtra po assignee (WS1,
    29.08.2026) — szuka WYŁĄCZNIE PO TYTULE dokładnego zadania kontrolnego tej
    roli (_control_task_title), nie działa na żadnym innym znalezionym
    zadaniu. Nie zgłaszać jako tego samego bugа co task_feedback_requester.py."""
    task_id = state.get("task_id")
    if task_id:
        return task_id
    title = _control_task_title(role)
    for t in client.list_tasks(project_id=admin_project_id):
        if t.get("title") == title:
            state["task_id"] = t["task_id"]
            return t["task_id"]
    new_id = client.create_task(title, CONTROL_DESCRIPTION, assigned_to="self", project_id=admin_project_id)
    state["task_id"] = new_id
    return new_id


def _task_status(client, task_id, admin_project_id):
    for t in client.list_tasks(project_id=admin_project_id):
        if t.get("task_id") == task_id:
            return t.get("status")
    return None  # zniknęło (usunięte ręcznie) — traktuj jak "nie znaleziono", nie zgaduj


def sync(client=None, role=None, force=False):
    """Priorytetowy check statusu zadania kontrolnego, tłumaczony na lokalną
    pauzę. Zwraca status zadania (str) albo None (throttled / błąd / zadanie
    nieznalezione / brak admin_project_id). Nigdy nie rzuca."""
    global _last_checked_at
    role = role or env_bootstrap._current_role()
    now = time.monotonic()
    if not force and _last_checked_at is not None and now - _last_checked_at < POLL_SECONDS:
        return None
    _last_checked_at = now

    try:
        client = client or get_client()
        admin_project_id = client.default_admin_project_id()
        if not admin_project_id:
            return None  # fail-closed: bez wiadomego projektu nie zgadujemy, nie tworzymy zadania
        state_path = _state_path_for_role(role)
        state = _load_state(state_path)
        task_id = _find_or_create_control_task(client, role, state, admin_project_id)
        status = _task_status(client, task_id, admin_project_id)
        if status is None and state.get("task_id") == task_id:
            # Żywy bug znaleziony 29.08.2026: zadanie kontrolne zniknęło (usunięte
            # ręcznie/gdzie indziej) — _find_or_create_control_task ufał cache'owi
            # BEZ WERYFIKACJI, więc mechanizm milczał na zawsze zamiast odtworzyć
            # zadanie. Czyścimy cache — NASTĘPNY sync utworzy je od nowa (nie
            # tworzymy TERAZ, żeby jeden przejściowy błąd sieci przy _task_status
            # nie zaczął mnożyć zadań kontrolnych).
            print(f"[remote_control] Zadanie kontrolne '{task_id}' ({role}) nie istnieje już w Projectly — "
                  "utworzę nowe przy następnym sprawdzeniu.")
            state.pop("task_id", None)
        _save_state(state, state_path)
    except Exception as exc:  # noqa: BLE001 — błąd sieci/Projectly nie może zmienić stanu pauzy
        print(f"[remote_control] Sprawdzenie zadania kontrolnego nie powiodło się ({role}): {exc}")
        return None

    reason = _pause_reason(role)
    if status == "done":
        if not control.is_paused():
            control.pause(reason=reason)
    elif status is not None and control.is_paused() and control.pause_reason() == reason:
        control.resume()
    return status


if __name__ == "__main__":
    print(sync(force=True))
    print("Stan po sync:", control.state(), "| powód:", control.pause_reason() or "-")
