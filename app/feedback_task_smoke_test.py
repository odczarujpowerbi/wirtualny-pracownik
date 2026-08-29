"""
Test dymny obsługi próśb o feedback: rozpoznanie (feedback_task), wykluczenia
przy zakładaniu (task_feedback_requester) i domknięcie bez modelu w runnerze
(runner_loop).

Pilnuje pętli z 29.08.2026: prośba o feedback wracała do kolejki bota jako
praca (0,20 USD i eskalacja do człowieka), a po domknięciu rodziła kolejną
("Feedback: Feedback: ..."). Sieci nie dotyka, baza tylko tymczasowa.

Użycie:
    python feedback_task_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import feedback_task
import state_store
import task_feedback_requester

AI = "AI - Dev"


def _zadanie(task_id, title, status="done", assignee="kacper", description=""):
    return {"task_id": task_id, "title": title, "status": status,
            "assignee": assignee, "description": description}


def _sprawdz_rozpoznanie():
    prosba_nowa = _zadanie("F-1", "Feedback: Odpowiedzi na maile od Oli",
                           description=feedback_task.opis_prosby_o_feedback())
    prosba_stara = _zadanie("F-2", "Feedback: Odpowiedzi na maile od Oli",
                            description=feedback_task.FEEDBACK_PYTANIE)
    zapetlona = _zadanie("F-3", "Feedback: Feedback: Odpowiedzi na maile od Oli",
                         description=feedback_task.opis_prosby_o_feedback())
    ludzka = _zadanie("F-4", "Feedback: uwagi klienta do raportu sprzedaży",
                      description="Klient przysłał uwagi po prezentacji, spisz je i rozdziel.")
    zwykla = _zadanie("F-5", "Odpowiedzi na maile od Oli", description="")

    return [
        ("prośba ze znacznikiem rozpoznana",
         feedback_task.czy_prosba_o_feedback(prosba_nowa)),
        ("prośba sprzed znacznika rozpoznana po tytule + treści pytania",
         feedback_task.czy_prosba_o_feedback(prosba_stara)),
        ("zapętlona prośba (podwójny prefiks) rozpoznana",
         feedback_task.czy_prosba_o_feedback(zapetlona)),
        ("zadanie człowieka z tytułem 'Feedback: ...' NIE jest prośbą",
         not feedback_task.czy_prosba_o_feedback(ludzka)),
        ("zwykłe zadanie NIE jest prośbą",
         not feedback_task.czy_prosba_o_feedback(zwykla)),
        ("zadanie na koncie AI rozpoznane jako wykonane przez bota",
         feedback_task.czy_wykonane_przez_konto_ai(_zadanie("F-6", "X", assignee=AI), AI)),
        ("zadanie człowieka NIE jest wykonane przez bota",
         not feedback_task.czy_wykonane_przez_konto_ai(zwykla, AI)),
        ("brak assignee NIE jest wykonane przez bota",
         not feedback_task.czy_wykonane_przez_konto_ai(_zadanie("F-7", "X", assignee=None), AI)),
        ("prefiks konta AI wczytany z configu",
         feedback_task.prefiks_konta_ai() == "AI - "),
    ]


def _sprawdz_wykluczenia():
    zadania = [
        _zadanie("T-1", "Weekly raportowanie sprzedaży"),                       # człowiek, done -> pytamy
        _zadanie("T-2", "Przygotować raport", status="in_progress"),            # niedomknięte
        _zadanie("T-3", "Już pytane"),                                          # w already_asked
        _zadanie("T-4", "Odpowiedzi na maile od Oli", assignee=AI),             # wykonane przez bota
        _zadanie("F-1", "Feedback: Weekly raportowanie sprzedaży",              # sama prośba o feedback
                 description=feedback_task.opis_prosby_o_feedback()),
    ]
    wybrane = task_feedback_requester.find_tasks_needing_feedback(
        zadania, already_asked={"T-3"}, ai_account_prefix=AI)
    ids = [t["task_id"] for t in wybrane]

    # Druga runda: gdyby prośba o feedback została domknięta, NIE wolno założyć
    # kolejnej ("Feedback: Feedback: ...") — to była właśnie pętla.
    domknieta_prosba = [_zadanie("F-1", "Feedback: Weekly raportowanie sprzedaży",
                                 description=feedback_task.opis_prosby_o_feedback())]
    po_domknieciu = task_feedback_requester.find_tasks_needing_feedback(
        domknieta_prosba, already_asked=set(), ai_account_prefix=AI)

    return [
        ("pytamy o domknięte zadanie człowieka", ids == ["T-1"]),
        ("nie pytamy o zadanie niedomknięte", "T-2" not in ids),
        ("nie pytamy drugi raz o to samo zadanie", "T-3" not in ids),
        ("nie pytamy o zadanie wykonane przez konto AI", "T-4" not in ids),
        ("nie pytamy o samą prośbę o feedback", "F-1" not in ids),
        ("domknięta prośba o feedback nie rodzi kolejnej", po_domknieciu == []),
    ]


class _KlientAtrapa:
    """Minimalny klient Projectly: zapamiętuje, co runner na nim wywołał."""

    def __init__(self):
        self.komentarze = []
        self.statusy = []
        self.utworzone = []

    def post_comment(self, task_id, text):
        self.komentarze.append((task_id, text))
        return True

    def update_status(self, task_id, status):
        self.statusy.append((task_id, status))
        return True

    def create_task(self, **kwargs):
        self.utworzone.append(kwargs)
        return "NIE-POWINNO-POWSTAC"


def _sprawdz_runner():
    """Runner domyka prośbę o feedback BEZ modelu, workera i eskalacji."""
    import runner_loop

    state_store.DB_PATH = Path(tempfile.mkdtemp()) / "test_state.db"

    def _nie_wolno(*args, **kwargs):
        raise AssertionError("prośba o feedback nie może uruchamiać modelu ani workera")

    oryginalny_thinker = runner_loop.task_thinker.think
    oryginalny_executor = runner_loop.executor.execute
    oryginalna_bramka_promptu = runner_loop.validator_prompt.check_prompt_safety
    oryginalny_zapis = runner_loop._save_result_to_onedrive
    try:
        runner_loop.task_thinker.think = _nie_wolno
        runner_loop.executor.execute = _nie_wolno
        # Ollama to usługa zewnętrzna (localhost:11434) — atrapa, żeby test był
        # szybki i dawał ten sam wynik z modelem lokalnym i bez niego.
        runner_loop.validator_prompt.check_prompt_safety = lambda text: {
            "safe": True, "confidence": 0.9, "detail": "atrapa"}
        # Zapis do OneDrive to ślad poboczny — test nie ma dotykać dysku użytkownika.
        runner_loop._save_result_to_onedrive = lambda task, status, comment: None

        klient = _KlientAtrapa()
        zadanie = {
            "task_id": "cmtab0y5w09d9x819ktki36wx",
            "title": "Feedback: Feedback: Odpowiedzi na maile od Oli",
            "description": feedback_task.opis_prosby_o_feedback(),
            "assignee": AI,
            "project_id": "PRJ",
        }
        wynik = runner_loop.process_task(zadanie, policy={}, routing={}, client=klient)
    finally:
        runner_loop.task_thinker.think = oryginalny_thinker
        runner_loop.executor.execute = oryginalny_executor
        runner_loop.validator_prompt.check_prompt_safety = oryginalna_bramka_promptu
        runner_loop._save_result_to_onedrive = oryginalny_zapis

    komentarz = klient.komentarze[0][1] if klient.komentarze else ""
    return [
        ("runner domyka prośbę o feedback jako done", wynik["status"] == "done"),
        ("runner nie klasyfikuje prośby jako ryzykownej", wynik["risk"] == "green"),
        ("runner ustawia status done w Projectly", ("cmtab0y5w09d9x819ktki36wx", "done") in klient.statusy),
        ("runner tłumaczy w komentarzu, dlaczego nie wykonuje", "prośba o feedback" in komentarz),
        ("runner nie zakłada zadania eskalacyjnego", klient.utworzone == []),
    ]


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = _sprawdz_rozpoznanie() + _sprawdz_wykluczenia() + _sprawdz_runner()

    print("\n--- Wynik testu dymnego feedback_task ---")
    all_passed = True
    for name, passed in checks:
        print(f"{'✅' if passed else '❌'} {name}")
        all_passed = all_passed and passed
    if not all_passed:
        print("\nCo najmniej jeden test nie przeszedł.")
        sys.exit(1)
    print("\nWszystkie testy przeszły.")


if __name__ == "__main__":
    run()
