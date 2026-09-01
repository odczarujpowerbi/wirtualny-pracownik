"""
Test dymny agent_supervisor.py — nadzorcy, który startuje TYLKO te role,
których zadanie sterujące w Projectly jest włączone. Zero sieci (klient
Projectly to atrapa) i zero realnie odpalonych procesów (launcher podmieniony).
Izoluje control.RUNS_DIR, remote_control._state_path_for_role, kill_switch
i scheduler_lock.is_running — zero wpływu na stan pauzy tej maszyny.

Użycie:
    python agent_supervisor_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import agent_supervisor as sup
import control
import kill_switch
import projectly_client
import remote_control as rc
import scheduler_lock


class _FakeClient:
    """Minimum, którego używa remote_control.sync: projekt administracyjny,
    lista zadań i tworzenie brakującego zadania sterującego."""

    def __init__(self, status="todo", admin_project_id="ADMIN-PROJ"):
        self._admin_project_id = admin_project_id
        self._status = status
        self._tasks = []

    def default_admin_project_id(self):
        return self._admin_project_id

    def list_tasks(self, project_id=None, include_control=False):
        return list(self._tasks)

    def create_task(self, title, description, assigned_to=None, project_id=None, **kwargs):
        task_id = f"CTRL-{len(self._tasks) + 1:03d}"
        self._tasks.append({"task_id": task_id, "title": title, "status": self._status})
        return task_id

    def update_status(self, task_id, status):
        """remote_control zaklada nowe zadanie sterujace jako WYLACZONE, wiec po
        create_task wola te metode. Atrapa celowo NIE nadpisuje tu statusu
        zadanego w konstruktorze - test steruje wlaczeniem/wylaczeniem przez
        _FakeClient(status=...), a nie przez sciezke tworzenia."""
        return True


class _BrokenClient(_FakeClient):
    def list_tasks(self, project_id=None, include_control=False):
        raise ConnectionError("Projectly niedostępne")


def _run_checks(tmp, uruchomione):
    """Zwraca listę (opis, warunek). tmp/uruchomione wstrzyknięte przez run()."""
    checks = []
    launcher = lambda role: (uruchomione.append(role) or {"started": True, "message": f"Uruchamiam '{role}'…"})

    def swiezy_start():
        """Każdy przypadek zaczyna od zera: pusta lista uruchomień, zdjęty
        throttling i USUNIĘTY zapamiętany task_id zadania sterującego. Bez tego
        ostatniego kolejne przypadki dla tej samej roli dostawały status None —
        stan wskazywał na zadanie z atrapy klienta poprzedniego przypadku."""
        uruchomione.clear()
        rc._last_checked_at = {}
        for plik in tmp.glob("remote_control_state_*.json"):
            plik.unlink()

    swiezy_start()
    # 1. Happy path: zadanie sterujące włączone (status 'todo'), proces nie
    #    działa -> nadzorca odpala bota.
    scheduler_lock.is_running = lambda role: False
    wpisy = sup.check_once(roles=["dev"], client_factory=lambda r: _FakeClient(status="todo"), launcher=launcher)
    checks.append(("włączone zadanie sterujące + bot nie działa -> START",
                   wpisy[0]["action"] == "start" and uruchomione == ["dev"]))

    # 2. Status 'done' (wyłączony w Projectly) -> nadzorca NIE startuje bota.
    swiezy_start()
    wpisy = sup.check_once(roles=["marketing"], client_factory=lambda r: _FakeClient(status="done"), launcher=launcher)
    checks.append(("wyłączone zadanie sterujące -> bot NIE startuje",
                   wpisy[0]["action"] == "wylaczony" and uruchomione == []))

    # 3. Bot już działa -> żadnego drugiego procesu (nie dublujemy).
    swiezy_start()
    scheduler_lock.is_running = lambda role: True
    wpisy = sup.check_once(roles=["dev"], client_factory=lambda r: _FakeClient(status="todo"), launcher=launcher)
    checks.append(("bot już działa -> bez drugiego procesu",
                   wpisy[0]["action"] == "dziala" and uruchomione == []))

    # 4. Error case: Projectly niedostępne -> brak statusu, nadzorca NIE
    #    startuje bota w ciemno (fail-soft, nie zgadujemy).
    swiezy_start()
    scheduler_lock.is_running = lambda role: False
    wpisy = sup.check_once(roles=["zarzad"], client_factory=lambda r: _BrokenClient(), launcher=launcher)
    checks.append(("błąd Projectly -> status None, bot NIE startuje",
                   wpisy[0]["status"] is None and wpisy[0]["action"] == "nieznany" and uruchomione == []))

    # 5. Error case: budowa klienta dla roli rzuca -> nadzorca to przeżywa i
    #    leci dalej (jedna zepsuta rola nie może ubić pętli nadzoru).
    swiezy_start()

    def _zly_klient(role):
        raise RuntimeError("brak tokenu")

    wpisy = sup.check_once(roles=["checker"], client_factory=_zly_klient, launcher=launcher)
    checks.append(("brak tokenu roli -> bez wyjątku, bot NIE startuje",
                   wpisy[0]["action"] == "nieznany" and uruchomione == []))

    # 6. Kill switch -> nie startuje NIKOGO, mimo włączonego zadania sterującego.
    swiezy_start()
    kill_switch.activate("test dymny")
    wpisy = sup.check_once(roles=["dev"], client_factory=lambda r: _FakeClient(status="todo"), launcher=launcher)
    kill_switch.deactivate()
    checks.append(("kill switch aktywny -> żadnego startu",
                   wpisy[0]["action"] == "stop" and uruchomione == []))

    # 7. Obca pauza lokalna (powód INNY niż marker remote_control, np. ręczne
    #    control.pause z terminala) -> mimo włączonego zadania sterującego
    #    nadzorca NIE startuje bota. Panel operatora od 01.09.2026 pauzuje już
    #    przez remote_control.set_enabled, więc jego pauzy tu nie ma — zostaje
    #    zabezpieczenie przed pauzą spoza tego mechanizmu.
    swiezy_start()
    control.pause(reason="Ręczne control.pause z terminala.", role="dev")
    wpisy = sup.check_once(roles=["dev"], client_factory=lambda r: _FakeClient(status="todo"), launcher=launcher)
    control.resume(role="dev")
    checks.append(("obca pauza lokalna -> nadzorca nie startuje bota",
                   wpisy[0]["action"] == "wstrzymany" and uruchomione == []))

    # 8. Tryb --status (start_enabled=False) -> pokazuje, kogo by odpalił, ale
    #    nie odpala.
    swiezy_start()
    wpisy = sup.check_once(roles=["dev"], client_factory=lambda r: _FakeClient(status="todo"),
                           launcher=launcher, start_enabled=False)
    checks.append(("tryb --status -> 'do-startu' zamiast realnego uruchomienia",
                   wpisy[0]["action"] == "do-startu" and uruchomione == []))

    # 9. Brak projektu administracyjnego (rola go nie widzi) -> status None,
    #    bez tworzenia zadania i bez startu.
    swiezy_start()
    wpisy = sup.check_once(roles=["dev"], client_factory=lambda r: _FakeClient(status="todo", admin_project_id=None),
                           launcher=launcher)
    checks.append(("brak projektu administracyjnego -> status None, bez startu",
                   wpisy[0]["status"] is None and uruchomione == []))

    # 9a-9d. Odczekanie i limit prob startu (obawa wlasciciela 01.09.2026 o
    #        "trzy okienka jednego bota" i o petle odpalania, ktora zjada maszyne).
    swiezy_start()
    sup._proby_startu.clear()
    scheduler_lock.is_running = lambda role: False
    # JEDNA instancja atrapy na cale te blok - kolejne przebiegi musza widziec
    # to samo zadanie sterujace, ktore utworzyl przebieg pierwszy (swieza atrapa
    # per wywolanie dawalaby status None i badalibysmy nie to, co chcemy).
    klient_trwaly = _FakeClient(status="todo")
    klient_wlaczony = lambda r: klient_trwaly

    sup.check_once(roles=["dev"], client_factory=klient_wlaczony, launcher=launcher)
    checks.append(("start: pierwsza proba odpala bota", uruchomione == ["dev"]))

    # Drugi przebieg OD RAZU po pierwszym: bot jeszcze nie wstal, ale nadzorca
    # NIE wola startu ponownie - czeka LAUNCH_COOLDOWN_SECONDS.
    wpisy = sup.check_once(roles=["dev"], client_factory=klient_wlaczony, launcher=launcher)
    checks.append(("start: drugi przebieg w oknie odczekania NIE odpala drugiego procesu",
                   wpisy[0]["action"] == "start-czekam" and uruchomione == ["dev"]))

    # Po uplywie odczekania probuje znowu, ale najwyzej MAX_LAUNCH_ATTEMPTS razy.
    for _ in range(sup.MAX_LAUNCH_ATTEMPTS + 2):
        sup._proby_startu["dev"]["ostatnia_proba"] = None  # symuluje uplyw odczekania
        wpisy = sup.check_once(roles=["dev"], client_factory=klient_wlaczony, launcher=launcher)
    checks.append((f"start: po {sup.MAX_LAUNCH_ATTEMPTS} nieudanych probach nadzorca sie poddaje (bez petli)",
                   wpisy[0]["action"] == "start-poddaje-sie"
                   and len(uruchomione) == sup.MAX_LAUNCH_ATTEMPTS))

    # Bot w koncu wstal -> licznik prob zerowany, nadzorca znow gotowy dzialac.
    scheduler_lock.is_running = lambda role: True
    sup.check_once(roles=["dev"], client_factory=klient_wlaczony, launcher=launcher)
    checks.append(("start: gdy bot wstanie, licznik nieudanych prob jest zerowany",
                   "dev" not in sup._proby_startu))

    # 10. Przelacznik z terminala (--wlacz/--wylacz) idzie ta sama droga co
    #     panel operatora: nieznana rola -> czytelny blad, bez wyjatku.
    swiezy_start()
    wynik_zla_rola = sup._przelacz("nieistniejaca-rola", True)
    checks.append(("--wlacz/--wylacz: nieznana rola -> ok=False, komunikat, bez wyjątku",
                   wynik_zla_rola["ok"] is False and "Nieznana rola" in wynik_zla_rola["message"]))

    # 11. print_status nie wywraca się na wpisie bez statusu (None).
    sup.print_status(wpisy)
    checks.append(("print_status radzi sobie ze statusem None", True))
    return checks


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    original_runs_dir = control.RUNS_DIR
    original_stop_flag = kill_switch.STOP_FLAG_PATH
    original_state_path = rc._state_path_for_role
    original_is_running = scheduler_lock.is_running

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        control.RUNS_DIR = tmp
        kill_switch.STOP_FLAG_PATH = tmp / "STOP.flag"
        rc._state_path_for_role = lambda role: tmp / f"remote_control_state_{role}.json"
        rc._last_checked_at = {}
        # Przypiete ID z prawdziwego configu nie moga wyciekac do testu (atrapa
        # klienta ich nie zna) — testujemy sciezke bez przypiecia.
        original_control_id = projectly_client.control_task_id_for_role
        projectly_client.control_task_id_for_role = lambda role: None
        try:
            checks = _run_checks(tmp, [])
        finally:
            control.RUNS_DIR = original_runs_dir
            kill_switch.STOP_FLAG_PATH = original_stop_flag
            rc._state_path_for_role = original_state_path
            projectly_client.control_task_id_for_role = original_control_id
            scheduler_lock.is_running = original_is_running
            rc._last_checked_at = {}

    print("\n--- Wynik testu dymnego nadzorcy ---")
    all_passed = True
    for opis, ok in checks:
        print(("✅ " if ok else "❌ ") + opis)
        all_passed = all_passed and ok
    return all_passed


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
