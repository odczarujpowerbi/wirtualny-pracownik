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

DWA KIERUNKI, jeden stan (01.09.2026):
    sync()        — czyta status z Projectly i odzwierciedla go w lokalnej pauzie,
    set_enabled() — zapisuje status w Projectly (panel operatora, terminal) i
                    domyka lokalną pauzę.
Oba tłumaczą status na pauzę jednym kodem (_apply_local_pause), więc panel,
terminal i Projectly nie mogą pokazywać różnych rzeczy.

sync() jest zachowawczy: resume() woła TYLKO gdy aktualny powód pauzy to marker
TEGO modułu (patrz `_pause_reason`), więc pauza założona spoza mechanizmu (ręczne
control.pause) nie zostanie cicho cofnięta. Jawna decyzja operatora przez
set_enabled() jest silniejsza i nadpisuje każdą pauzę (patrz `_wymus_lokalnie`).

Zadania sterujące są ODSIANE z kolejki pracy — filtr siedzi w projectly_client
(is_control_task / CONTROL_TASK_TITLE_PREFIX), a ten moduł jest jedynym, który
prosi o nie jawnie (list_tasks(include_control=True)). Bez tego bot brał własny
przełącznik jako zadanie do wykonania.

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
import projectly_client
from projectly_client import get_client

POLL_SECONDS = 15

CONTROL_DESCRIPTION = (
    "Zadanie sterujące tym botem z poziomu Projectly (dodane 29.08.2026, decyzja "
    "właściciela). Status 'Done' = bot WSTRZYMANY — nie podejmuje nowej pracy, "
    "aktualne zadanie kończy się samo. Każdy inny status (todo/in_progress) = "
    "bot pracuje normalnie. Sprawdzane priorytetowo na początku każdego cyklu "
    "schedulera — przed jakimkolwiek innym zadaniem."
)

# Throttling w pamięci procesu (nie w pliku), PER ROLA (01.09.2026). Wcześniej
# jedna wspólna zmienna na cały moduł wystarczała, bo każdy proces bota pytał
# tylko o SWOJĄ rolę. agent_supervisor.py odpytuje w jednym procesie wszystkie
# cztery role po kolei — przy wspólnym liczniku pierwsza rola ustawiała go dla
# wszystkich i trzy pozostałe wracały natychmiast z None (nigdy nie sprawdzone).
_last_checked_at = {}


def _control_task_title(role):
    """Prefiks bierzemy z projectly_client (CONTROL_TASK_TITLE_PREFIX) — tam
    siedzi filtr odsiewający te zadania z kolejki pracy, więc tytuł i filtr nie
    mogą się rozjechać po zmianie w jednym miejscu."""
    return f"{projectly_client.CONTROL_TASK_TITLE_PREFIX} {role}"


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
    """ID zadania sterującego tą rolą. Kolejność: PRZYPIĘTE w configu →
    zapamiętane lokalnie → szukanie po tytule → utworzenie nowego.

    Przypięte ID (config/projectly.yaml → control_task_by_role, 01.09.2026) ma
    bezwarunkowe pierwszeństwo i wyłącza trzy dalsze kroki: żadnego zgadywania
    po tytule, żadnego tworzenia, żadnych duplikatów. Powód jest twardy —
    zadanie tworzone od zera dostaje w Projectly status "todo", czyli WŁĄCZONY,
    więc gubienie i odtwarzanie przełącznika cicho włączało boty (trzy z czterech
    wróciły na "włączony" po wyłączeniu, 01.09.2026).

    Ścieżka bez configu została dla roli bez wpisu, ale nowe zadanie zakłada się
    teraz jako WYŁĄCZONE (fail-closed) — nie chcemy, żeby samo pojawienie się
    przełącznika uruchamiało bota.

    list_tasks(project_id=...) świadomie bez filtra po assignee (WS1,
    29.08.2026) — szuka WYŁĄCZNIE PO TYTULE dokładnego zadania kontrolnego tej
    roli (_control_task_title), nie działa na żadnym innym znalezionym
    zadaniu. Nie zgłaszać jako tego samego bugа co task_feedback_requester.py."""
    przypiete = projectly_client.control_task_id_for_role(role)
    if przypiete:
        return przypiete
    task_id = state.get("task_id")
    if task_id:
        return task_id
    title = _control_task_title(role)
    for t in client.list_tasks(project_id=admin_project_id, include_control=True):
        if t.get("title") == title:
            state["task_id"] = t["task_id"]
            return t["task_id"]
    new_id = client.create_task(title, CONTROL_DESCRIPTION, assigned_to="self", project_id=admin_project_id)
    client.update_status(new_id, "done")  # fail-closed: nowy przełącznik = WYŁĄCZONY
    print(f"[remote_control] Utworzyłem zadanie sterujące '{title}' jako WYŁĄCZONE "
          f"({new_id}) — przypnij to ID w config/projectly.yaml → control_task_by_role.")
    state["task_id"] = new_id
    return new_id


def _task_status(client, task_id, admin_project_id):
    """Status zadania sterującego. Najpierw projekt administracyjny (jedno
    zapytanie), a gdy tam go nie ma — szerzej, po wszystkich pollowanych
    projektach. Ten drugi krok dodany 01.09.2026: przypięte ID przestaje wtedy
    zależeć od tego, w którym projekcie właściciel trzyma przełącznik
    (przeniesienie zadania w Projectly nie może zepsuć sterowania).

    Zwraca None, gdy zadania nie ma NIGDZIE — wtedy nie zgadujemy."""
    for t in client.list_tasks(project_id=admin_project_id, include_control=True):
        if t.get("task_id") == task_id:
            return t.get("status")
    for t in client.list_tasks(include_control=True):
        if t.get("task_id") == task_id:
            return t.get("status")
    return None


def sync(client=None, role=None, force=False):
    """Priorytetowy check statusu zadania kontrolnego, tłumaczony na lokalną
    pauzę. Zwraca status zadania (str) albo None (throttled / błąd / zadanie
    nieznalezione / brak admin_project_id). Nigdy nie rzuca."""
    role = role or env_bootstrap._current_role()
    now = time.monotonic()
    poprzednio = _last_checked_at.get(role)
    if not force and poprzednio is not None and now - poprzednio < POLL_SECONDS:
        return None
    _last_checked_at[role] = now

    try:
        client = client or get_client()
        admin_project_id = client.default_admin_project_id()
        if not admin_project_id:
            return None  # fail-closed: bez wiadomego projektu nie zgadujemy, nie tworzymy zadania
        state_path = _state_path_for_role(role)
        state = _load_state(state_path)
        task_id = _find_or_create_control_task(client, role, state, admin_project_id)
        status = _task_status(client, task_id, admin_project_id)
        if status is None and projectly_client.control_task_id_for_role(role):
            # ID przypięte w configu, a Projectly go nie zna (usunięte, literówka,
            # inny tenant). NIE zakładamy nowego — nowe byłoby "todo", czyli
            # WŁĄCZONY, i cicho uruchomiłoby bota. Zwracamy None: nadzorca zostawia
            # wszystko jak jest i widać to w logu.
            print(f"[remote_control] Przypięte zadanie sterujące '{task_id}' ({role}) nie istnieje w Projectly — "
                  "popraw config/projectly.yaml → control_task_by_role. Nie zmieniam stanu bota.")
        elif status is None and state.get("task_id") == task_id:
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

    _apply_local_pause(role, status)
    return status


def _apply_local_pause(role, status):
    """Tłumaczy status zadania sterującego na lokalną pauzę TEJ roli. Jedyne
    miejsce, które to robi — wołane i przez sync() (odczyt z Projectly), i przez
    set_enabled() (zapis do Projectly), żeby oba kierunki dawały ten sam stan.

    role= przekazywane jawnie do control.* (01.09.2026). Wcześniej te wywołania
    szły bez roli, czyli na rolę BIEŻĄCEGO PROCESU — poprawnie, dopóki jedynym
    wywołującym był job_scheduler.py (sync(role=CURRENT_ROLE), zawsze własna
    rola). agent_supervisor.py i dashboard.py działają na CUDZYCH rolach z
    jednego procesu i bez tego wstrzymywałyby nie tego bota, co trzeba."""
    reason = _pause_reason(role)
    if status == "done":
        if not control.is_paused(role=role):
            control.pause(reason=reason, role=role)
    elif status is not None and control.is_paused(role=role) and control.pause_reason(role=role) == reason:
        control.resume(role=role)


def _wymus_lokalnie(role, enabled):
    """Lokalna pauza wg JAWNEJ decyzji operatora — inaczej niż _apply_local_pause,
    które tylko odzwierciedla odczytany status i celowo nie rusza cudzej pauzy.

    Tu nadpisujemy stan bez pytania o powód: "włącz" zdejmuje KAŻDĄ pauzę tej
    roli, "wyłącz" ustawia powód na marker tego modułu. Bez tego pauza założona
    poza tym mechanizmem (np. flaga z panelu sprzed 01.09.2026, z innym tekstem
    powodu) byłaby nie do zdjęcia: sync() wznawia tylko własny marker, więc bot
    zostawałby wstrzymany na zawsze, mimo włączonego zadania sterującego."""
    if enabled:
        control.resume(role=role)
    else:
        control.pause(reason=_pause_reason(role), role=role)


def set_enabled(role, enabled, client=None):
    """Włącza/wyłącza bota TEJ roli — zapisuje status zadania sterującego w
    Projectly i od razu domyka lokalną pauzę tym samym kodem, co odczyt.
    Zwraca {"ok", "status", "message"}, nigdy nie rzuca.

    To jest jedyna droga wyłączania bota z panelu operatora (dashboard.py).
    Do 01.09.2026 panel pisał WYŁĄCZNIE lokalną flagę pauzy z własnym tekstem
    powodu, a Projectly o niczym nie wiedziało — dwa niezależne przełączniki
    tego samego bota, rozjeżdżające się po pierwszym kliknięciu (realny stan tej
    maszyny: panel mówił "wyłączony", zadanie sterujące "todo"/włączony).

    Zachowanie przy błędzie Projectly jest świadomie ASYMETRYCZNE, w stronę
    bezpiecznego kierunku:
      - wyłączanie -> pauza zakładana lokalnie MIMO błędu (użytkownik prosił o
        stop; ostrzegamy, że nadzorca może bota wznowić, bo źródło prawdy wciąż
        mówi "włączony"),
      - włączanie  -> lokalnie NIC nie ruszamy (fail-closed: nie uruchamiamy
        bota, kiedy nie wiemy, co mówi zadanie sterujące)."""
    status = "todo" if enabled else "done"
    czynnosc = "włączony" if enabled else "wyłączony"
    try:
        client = client or projectly_client.client_for_role(role)
        admin_project_id = client.default_admin_project_id()
        if not admin_project_id:
            return {"ok": False, "status": None, "message": (
                f"Rola '{role}' nie widzi projektu administracyjnego w Projectly — "
                "nie mam gdzie trzymać zadania sterującego (sprawdź default_admin_project_by_role)."
            )}
        state_path = _state_path_for_role(role)
        state = _load_state(state_path)
        task_id = _find_or_create_control_task(client, role, state, admin_project_id)
        client.update_status(task_id, status)
        _save_state(state, state_path)
        # WERYFIKACJA ODCZYTEM (01.09.2026). update_task w Projectly zwraca sukces
        # także dla ID, którego nie ma — więc bez tego set_enabled meldował
        # "bot wyłączony", a w Projectly nie zmieniało się nic. Realnie zmyliło to
        # i mnie, i właściciela: cztery przełączniki "wyłączone", z czego dwa
        # nieistniejące, a dwa dalej na "todo".
        po_zapisie = _task_status(client, task_id, admin_project_id)
        if po_zapisie != status:
            return {"ok": False, "status": po_zapisie, "message": (
                f"Zapis statusu dla '{role}' NIE zadziałał: po zapisie zadanie '{task_id}' "
                f"ma status {po_zapisie or 'BRAK (zadanie nie istnieje)'}, a miało mieć '{status}'. "
                "Sprawdź config/projectly.yaml → control_task_by_role. Stanu bota nie zmieniam."
            )}
    except Exception as exc:  # noqa: BLE001 — panel operatora ma pokazać błąd, nie wywalić się
        if enabled:
            return {"ok": False, "status": None, "message": (
                f"Nie udało się włączyć bota '{role}' — zapis do Projectly nie powiódł się ({exc}). "
                "Lokalnie nic nie zmieniam, żeby bot nie wstał wbrew zadaniu sterującemu."
            )}
        _wymus_lokalnie(role, enabled=False)
        return {"ok": False, "status": "done", "message": (
            f"Bot '{role}' wyłączony LOKALNIE, ale zapis do Projectly nie powiódł się ({exc}). "
            "Zadanie sterujące nadal mówi 'włączony', więc nadzorca może go wznowić — powtórz, gdy Projectly wróci."
        )}

    _wymus_lokalnie(role, enabled)
    # Zdejmujemy throttling TEJ roli: najbliższy sync ma przeczytać świeżo
    # zapisany status, a nie wrócić z None przez okno POLL_SECONDS.
    _last_checked_at.pop(role, None)
    return {"ok": True, "status": status,
            "message": f"Bot '{role}' {czynnosc} — zadanie sterujące w Projectly ustawione na '{status}'."}


if __name__ == "__main__":
    print(sync(force=True))
    print("Stan po sync:", control.state(), "| powód:", control.pause_reason() or "-")
