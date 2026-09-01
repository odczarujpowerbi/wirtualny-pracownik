"""
Nadzorca — JEDYNY proces, który ma domyślnie działać na maszynie (decyzja
właściciela 01.09.2026). Nie wykonuje żadnych zadań, nie woła modelu, nie
kosztuje: co POLL_SECONDS czyta status zadania sterującego każdej roli w
Projectly ("🎛️ Kontrola bota: <rola>") i na tej podstawie ODPALA proces bota,
który ma być włączony. Boty wyłączone po prostu nie istnieją jako procesy.

Odwrócenie dotychczasowego układu. Wcześniej cała czwórka (dev/checker/
marketing/zarzad) startowała z Harmonogramu zadań Windows przy logowaniu, a
zadanie sterujące potrafiło je tylko WSTRZYMAĆ — bo remote_control.sync()
działa WEWNĄTRZ job_scheduler.py, więc żeby bota dało się zdalnie włączyć,
musiał już chodzić i zjadać pamięć. Teraz jest odwrotnie: przy logowaniu
startuje wyłącznie ten plik, a bot rusza dopiero, gdy jego zadanie sterujące
jest włączone.

Mapowanie statusu — dokładnie to samo, co w remote_control.py (świadomie nie
druga konwencja):
    status "done"     -> bot WYŁĄCZONY (nie startujemy; działającego wstrzyma
                         remote_control.sync, jak dotąd)
    każdy inny status -> bot WŁĄCZONY (todo/in_progress; startujemy, jeśli
                         jeszcze nie działa)
    brak statusu      -> NIC nie robimy (błąd sieci, brak projektu
                         administracyjnego, zadanie nieznalezione). Fail-soft:
                         chwilowa niedostępność Projectly nie może ani ubić
                         bota, ani go samoczynnie odpalić.

Sterowanie działa też LOKALNIE, bez Projectly: pauza z panelu operatora
(dashboard.py -> control.pause) blokuje start, bo `control.is_paused(role)`
jest sprawdzane po sync(). Zdjęcie tamtej pauzy ("Włącz" w dashboardzie)
sprawia, że najbliższy przebieg nadzorcy odpali bota. Kill switch
(kill_switch.py) wstrzymuje starty wszystkich ról naraz.

Uruchomienie:
    python agent_supervisor.py            # pętla nadzoru (tak startuje .bat)
    python agent_supervisor.py --status   # tylko wypisz stan i zakończ
"""

import time

import agent_launcher
import control
import env_bootstrap  # noqa: F401  # wczytuje secrets/.env (UTF-8 na stdout + token Projectly)
import kill_switch
import projectly_client
import remote_control
import scheduler_lock

POLL_SECONDS = 30

# Po próbie odpalenia bota nie próbujemy ponownie przez ten czas (01.09.2026,
# obawa właściciela o "trzy okienka jednego bota"). Dwa realne problemy, które
# to zamyka:
#   1. Wyścig startu — proces potrzebuje kilkudziesięciu sekund na import
#      wszystkich modułów, zanim zajmie blokadę (scheduler_lock). Bez odczekania
#      nadzorca widziałby "nie działa" i odpalał drugi proces; jeden z nich i tak
#      by padł na blokadzie, ale po co go wołać.
#   2. Pętla odpalania — bot, który wywala się na starcie (zła konfiguracja, brak
#      biblioteki), byłby odpalany co POLL_SECONDS bez końca. To właśnie tak
#      zjada maszynę.
LAUNCH_COOLDOWN_SECONDS = 180

# Po tylu nieudanych próbach z rzędu nadzorca PRZESTAJE próbować dla tej roli i
# mówi to w logu. Fail-closed: lepiej niech bot nie wstanie i będzie o tym
# wiadomo, niż niech maszyna orze w kółko. Licznik zeruje się, gdy bot wstanie.
MAX_LAUNCH_ATTEMPTS = 3

# Rola -> {"ostatnia_proba": monotonic, "proby": int}. W pamięci procesu, nie w
# pliku — nadzorca jest jednym, długo żyjącym procesem, a po jego restarcie
# ponowna próba jest wręcz pożądana.
_proby_startu = {}


def _decide(role, status, is_running, is_paused, stop_active):
    """Czysta decyzja (bez efektów ubocznych, dlatego testowalna wprost):
    (akcja, opis). Akcja "start" oznacza "odpal proces tej roli", każda inna
    oznacza "nic nie rób"."""
    if stop_active:
        return "stop", "kill switch aktywny — nie startuję nikogo"
    if status is None:
        return "nieznany", "brak statusu z Projectly — zostawiam jak jest"
    if status == "done":
        return ("wylaczony-dziala", "wyłączony w Projectly — działający proces wstrzyma się sam") \
            if is_running else ("wylaczony", "wyłączony w Projectly")
    if is_running:
        return "dziala", "włączony i działa"
    if is_paused:
        return "wstrzymany", f"włączony w Projectly, ale wstrzymany lokalnie ({control.pause_reason(role=role)})"
    return "start", "włączony w Projectly, a proces nie działa — odpalam"


def _status_for_role(role, client_factory):
    """Status zadania sterującego roli. remote_control.sync() robi przy okazji
    to, co robił dotąd wewnątrz bota (ustawia/zdejmuje pauzę tej roli), więc
    nadzorca nie powiela logiki pauzy — pyta tylko o wynik. Nigdy nie rzuca:
    sync() jest fail-soft, a błąd budowy klienta łapiemy tutaj."""
    try:
        client = client_factory(role)
    except Exception as exc:  # noqa: BLE001 — brak/zły token jednej roli nie może ubić nadzorcy
        print(f"[nadzorca] Nie udało się zbudować klienta Projectly dla roli '{role}': {exc}")
        return None
    return remote_control.sync(client=client, role=role, force=True)


def check_once(roles=None, client_factory=None, launcher=None, start_enabled=True):
    """Jeden przebieg nadzoru nad wszystkimi rolami. Zwraca listę wpisów
    {role, status, running, action, detail} — to samo, co wypisuje --status.
    client_factory i launcher wstrzykiwalne (testy dymne: zero sieci, zero
    realnie odpalonych procesów). start_enabled=False (tryb --status) tylko
    pokazuje, kogo nadzorca by odpalił — sam nie odpala nikogo.

    UWAGA: nawet przy start_enabled=False przebieg NIE jest w pełni bez
    efektów — remote_control.sync() może założyć brakujące zadanie sterujące
    w Projectly i ustawić/zdjąć pauzę roli. To celowe: pauza ma jedno źródło
    prawdy (remote_control.py), nadzorca jej nie powiela."""
    roles = roles if roles is not None else list(agent_launcher.AGENT_BAT_FILES)
    client_factory = client_factory or projectly_client.client_for_role
    launcher = launcher or agent_launcher.start_agent
    stop_active = kill_switch.is_active()

    wpisy = []
    for role in roles:
        status = _status_for_role(role, client_factory)
        is_running = scheduler_lock.is_running(role)
        if is_running:
            _proby_startu.pop(role, None)  # wstał — licznik nieudanych prób do zera
        action, detail = _decide(role, status, is_running, control.is_paused(role=role), stop_active)
        if action == "start" and not start_enabled:
            action, detail = "do-startu", "włączony w Projectly — wystartuje przy najbliższym przebiegu nadzorcy"
        elif action == "start":
            action, detail = _sprobuj_start(role, launcher)
        wpisy.append({"role": role, "status": status, "running": is_running, "pid": scheduler_lock.running_pid(role),
                      "action": action, "detail": detail})
    return wpisy


def _sprobuj_start(role, launcher, teraz=None):
    """Odpala bota, ale z odczekaniem i limitem prób — patrz
    LAUNCH_COOLDOWN_SECONDS i MAX_LAUNCH_ATTEMPTS. Zwraca (akcja, opis).

    Sam launcher (agent_launcher.start_agent) i tak pyta scheduler_lock, czy bot
    nie działa, a job_scheduler.py zajmuje blokadę na starcie i wychodzi, gdy
    zastanie żywą instancję — to są dwa zabezpieczenia przed DWOMA procesami tej
    samej roli. To tutaj jest trzecie i pilnuje czegoś innego: żeby nadzorca nie
    WOŁAŁ startu w kółko, kiedy bot nie wstaje."""
    teraz = teraz if teraz is not None else time.monotonic()
    wpis = _proby_startu.setdefault(role, {"ostatnia_proba": None, "proby": 0})

    if wpis["proby"] >= MAX_LAUNCH_ATTEMPTS:
        return "start-poddaje-sie", (
            f"bot '{role}' nie wstał po {MAX_LAUNCH_ATTEMPTS} próbach — przestaję próbować. "
            "Odpal ręcznie (start-agent-<rola>.bat) i zobacz, na czym się wywala."
        )
    if wpis["ostatnia_proba"] is not None and teraz - wpis["ostatnia_proba"] < LAUNCH_COOLDOWN_SECONDS:
        czekam = int(LAUNCH_COOLDOWN_SECONDS - (teraz - wpis["ostatnia_proba"]))
        return "start-czekam", f"start '{role}' już zlecony, daję mu jeszcze {czekam}s na podniesienie się"

    wpis["ostatnia_proba"] = teraz
    wpis["proby"] += 1
    wynik = launcher(role)
    if not wynik["started"]:
        return "start-nieudany", wynik["message"]
    return "start", f"{wynik['message']} (próba {wpis['proby']}/{MAX_LAUNCH_ATTEMPTS})"


def print_status(wpisy):
    print(f"{'Rola':<12}{'Zadanie sterujące':<24}{'Proces':<20}{'Akcja':<18}Szczegóły")
    for w in wpisy:
        status = w["status"] or "—"
        wlaczony = "wyłączony" if status == "done" else ("—" if status == "—" else "włączony")
        proces = f"działa (PID {w['pid']})" if w["running"] else "nie działa"
        print(f"{w['role']:<12}{wlaczony + ' (' + status + ')':<24}"
              f"{proces:<20}{w['action']:<18}{w['detail']}")
    print()
    print(f"Procesów job_scheduler.py na maszynie: {_ile_procesow_schedulera()} "
          f"(powinno być tyle, ile ról z 'działa' wyżej — inaczej ktoś odpalił bota ręcznie obok nadzorcy)")


def _ile_procesow_schedulera():
    """Liczba żywych procesów job_scheduler.py, LICZONA NIEZALEŻNIE od plików
    blokady — właśnie po to, żeby wykryć proces, który blokady nie trzyma.
    Bez psutil zwraca None (nie zgadujemy)."""
    try:
        import psutil
    except ImportError:
        return None
    ile = 0
    for proc in psutil.process_iter(["cmdline"]):
        try:
            if "job_scheduler" in " ".join(proc.info["cmdline"] or []).lower():
                ile += 1
        except psutil.Error:
            continue
    return ile


def run(poll_seconds=POLL_SECONDS):
    print(f"Nadzorca wystartował — sprawdzam zadania sterujące co {poll_seconds}s. "
          "Boty startują same, gdy ich zadanie sterujące w Projectly jest włączone "
          "(status inny niż 'done').")
    try:
        while True:
            for w in check_once():
                # Cisza dla stanu ustalonego (działa / wyłączony) — w logu mają
                # zostać wyłącznie zmiany i problemy, żeby okno nadzorcy dało się
                # czytać po tygodniu pracy.
                if w["action"] not in ("dziala", "wylaczony"):
                    print(f"[nadzorca] {w['role']}: {w['detail']}")
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("Nadzorca zatrzymany ręcznie. Boty, które już działają, działają dalej.")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Nadzorca botów — startuje tylko te role, "
                                                 "których zadanie sterujące w Projectly jest włączone.")
    parser.add_argument("--status", action="store_true",
                        help="Tylko sprawdź i wypisz stan zadań sterujących, nie odpalaj pętli")
    parser.add_argument("--wlacz", metavar="ROLA",
                        help="Włącz bota tej roli (ustawia status zadania sterującego w Projectly)")
    parser.add_argument("--wylacz", metavar="ROLA",
                        help="Wyłącz bota tej roli (ustawia status zadania sterującego na 'done')")
    parser.add_argument("--poll", type=int, default=POLL_SECONDS,
                        help=f"Co ile sekund sprawdzać (domyślnie {POLL_SECONDS})")
    args = parser.parse_args()

    # --wlacz/--wylacz idą DOKŁADNIE tą samą drogą co przyciski w panelu
    # operatora (remote_control.set_enabled) — terminal i panel nie mogą być
    # dwoma osobnymi przełącznikami tego samego bota.
    for rola, wlaczony in ((args.wlacz, True), (args.wylacz, False)):
        if rola:
            print(_przelacz(rola, wlaczony)["message"])
            return
    if args.status:
        print_status(check_once(start_enabled=False))
        return
    run(poll_seconds=args.poll)


def _przelacz(role, enabled):
    if role not in agent_launcher.AGENT_BAT_FILES:
        return {"ok": False, "message": f"Nieznana rola '{role}' "
                                        f"(znane: {', '.join(agent_launcher.AGENT_BAT_FILES)})."}
    return remote_control.set_enabled(role, enabled=enabled)


if __name__ == "__main__":
    main()
