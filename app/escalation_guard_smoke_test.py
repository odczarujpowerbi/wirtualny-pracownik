"""
Test dymny bramki na zadania eskalacyjne (runner_loop._odloz_zadanie_eskalacyjne
+ escalation.is_escalation_task).

Czego pilnuje: zadanie eskalacyjne, które wróciło do kolejki agenta, NIE jest
przez niego wykonywane ani eskalowane ponownie. Bez tego runner zamykał je jako
needs_approval cykl po cyklu (żywy przebieg: 'Wymaga decyzji: Alert: stan
maszyny wymaga sprawdzenia', osiem domknięć pod rząd na jednym zadaniu).

Używa TYMCZASOWEJ bazy (podmiana state_store.DB_PATH), żeby nie dotykać żywego
runs/state.db. Wpina się automatycznie w self_check.py (glob *_smoke_test.py).
"""

import tempfile
from pathlib import Path

import escalation
import runner_loop
import state_store


class KlientKtoryNieMozeBycUzyty:
    """Każde dotknięcie Projectly przy zadaniu eskalacyjnym to błąd, więc atrapa
    wywala się na każdej metodzie zamiast po cichu przyjmować wywołanie."""

    def __getattr__(self, name):
        def bum(*args, **kwargs):
            raise AssertionError(f"Zadanie eskalacyjne nie powinno wołać client.{name}()")
        return bum


def _use_temp_db():
    state_store.DB_PATH = Path(tempfile.mkdtemp()) / "test_state.db"


def _zadanie_eskalacyjne():
    return {
        "task_id": "PRJ-ESC-0001",
        "title": "Wymaga decyzji: Alert: stan maszyny wymaga sprawdzenia",
        "description": (
            f"{escalation.ESCALATION_MARKER}\nZadanie źródłowe: PRJ-0100\n"
            "Co jest potrzebne: decyzja człowieka"
        ),
    }


def test_rozpoznanie_zadania_eskalacyjnego():
    assert escalation.is_escalation_task(_zadanie_eskalacyjne()) is True

    # Sam przedrostek tytułu wystarczy: zadania eskalacyjne założone przed
    # dołożeniem znacznika leżą już w Projectly i to one zapętliły runner.
    stare = {"task_id": "PRJ-ESC-0000", "title": "Wymaga decyzji: Coś sprzed znacznika"}
    assert escalation.is_escalation_task(stare) is True

    zwykle = {"task_id": "PRJ-0001", "title": "Sprawdź plik testowy INDEKA"}
    assert escalation.is_escalation_task(zwykle) is False

    # Kontynuacja to praca DLA BOTA (continuation_task_creator) — musi przejść.
    kontynuacja = {"task_id": "PRJ-0002", "title": "Kontynuacja: Sprawdź plik testowy INDEKA"}
    assert escalation.is_escalation_task(kontynuacja) is False
    print("OK  is_escalation_task rozpoznaje eskalacje i przepuszcza zwykłe zadania")


def test_escalate_to_human_znakuje_opis():
    """Nowe eskalacje muszą nieść znacznik, żeby rozpoznanie nie wisiało wyłącznie
    na tytule (człowiek może go przepisać)."""
    _use_temp_db()
    utworzone = {}

    class KlientZapisujacy:
        def create_task(self, title, description, **kwargs):
            utworzone.update({"title": title, "description": description})
            return "PRJ-ESC-0007"

    escalation.escalate_to_human(
        {"task_id": "PRJ-0100", "title": "Alert: stan maszyny wymaga sprawdzenia"},
        "decyzja człowieka", KlientZapisujacy())

    assert utworzone["title"].startswith(escalation.ESCALATION_TITLE_PREFIX), utworzone["title"]
    assert escalation.ESCALATION_MARKER in utworzone["description"], utworzone["description"]
    assert escalation.is_escalation_task(
        {"task_id": "PRJ-ESC-0007", "title": utworzone["title"], "description": utworzone["description"]}
    ) is True
    print("OK  escalate_to_human znakuje utworzone zadanie eskalacyjne")


def test_runner_odklada_zadanie_eskalacyjne():
    _use_temp_db()
    task = _zadanie_eskalacyjne()

    wynik = runner_loop.process_task(task, policy={}, routing={}, client=KlientKtoryNieMozeBycUzyty())

    assert wynik["status"] == runner_loop.STATUS_CZEKA_NA_CZLOWIEKA, wynik
    typy = [e["event_type"] for e in state_store.get_events(task["task_id"])]
    assert "escalation_task_skipped" in typy, typy
    # Kluczowe: brak domknięcia bloku, bo agent NIC nie wykonał ani nie zamknął.
    assert "block_closed" not in typy, typy
    print("OK  runner odkłada zadanie eskalacyjne bez wykonywania i bez block_closed")


def test_ponowne_pollowanie_nie_dubluje_zdarzenia():
    """Zadanie czekające na decyzję wraca w każdym cyklu pollowania — dziennik
    ma dostać JEDEN wpis, nie tysiąc."""
    _use_temp_db()
    task = _zadanie_eskalacyjne()
    klient = KlientKtoryNieMozeBycUzyty()

    for _ in range(5):
        runner_loop.process_task(task, policy={}, routing={}, client=klient)

    skipy = [e for e in state_store.get_events(task["task_id"])
             if e["event_type"] == "escalation_task_skipped"]
    assert len(skipy) == 1, f"oczekiwano 1 wpisu pominięcia, jest {len(skipy)}"
    print("OK  powtórne pollowanie tego samego zadania nie dubluje wpisów w dzienniku")


if __name__ == "__main__":
    test_rozpoznanie_zadania_eskalacyjnego()
    test_escalate_to_human_znakuje_opis()
    test_runner_odklada_zadanie_eskalacyjne()
    test_ponowne_pollowanie_nie_dubluje_zdarzenia()
    print("\nWszystkie testy bramki eskalacyjnej przeszły.")
