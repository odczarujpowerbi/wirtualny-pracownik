"""
Test dymny task_decomposer.py. Zero sieci — task_thinker.ask_model jest
podmieniany atrapą, klient Projectly atrapą zbierającą wywołania create_task,
żeby sprawdzić parsowanie/walidację/fail-closed i tworzenie podzadań bez
prawdziwego wywołania modelu ani MCP.

Użycie:
    python task_decomposer_smoke_test.py
"""

import sys

import task_decomposer
import task_thinker

TASK = {"task_id": "T-DUZE", "title": "Przygotuj pełny audyt konkurencji i raport",
        "expected_result": "Raport z analizą konkurencji", "project_id": "PROJ-1"}


def _atrapa(text, available=True, source="claude_code"):
    return lambda prompt, caller=None: {"available": available, "text": text,
                                        "source": source, "detail": "OK"}


class _FakeClient:
    def __init__(self):
        self.created = []
        self._next_id = 1

    def create_task(self, title, description, assigned_to, subtask_of=None, order=None, project_id=None):
        new_id = f"CHILD-{self._next_id}"
        self._next_id += 1
        self.created.append({"task_id": new_id, "title": title, "description": description,
                             "assigned_to": assigned_to, "subtask_of": subtask_of,
                             "order": order, "project_id": project_id})
        return new_id


def _json_z_podzadaniami(n, split=True):
    subtasks = ", ".join(
        f'{{"title": "Podzadanie {i+1}", "description": "Opis {i+1}"}}' for i in range(n)
    )
    return f'{{"split": {str(split).lower()}, "reasoning": "Zbyt duże na jeden krok.", "subtasks": [{subtasks}]}}'


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_ask_model = task_thinker.ask_model

    try:
        # 1. Happy path: model chce rozbić na 3 podzadania.
        task_thinker.ask_model = _atrapa(_json_z_podzadaniami(3))
        decyzja = task_decomposer.decide(TASK)
        checks.append(("Happy path: should_split=True", decyzja["should_split"] is True))
        checks.append(("Happy path: 3 podzadania", len(decyzja["subtasks"]) == 3))
        checks.append(("Happy path: koszt policzony (claude_code proxy > 0)", decyzja["cost_usd"] > 0))

        # 2. Model mówi "nie dziel" -> should_split=False, subtasks=[].
        task_thinker.ask_model = _atrapa(_json_z_podzadaniami(3, split=False))
        decyzja_nie = task_decomposer.decide(TASK)
        checks.append(("split=False z modelu -> should_split=False", decyzja_nie["should_split"] is False))
        checks.append(("split=False -> brak podzadań", decyzja_nie["subtasks"] == []))

        # 3. Guard: model chce podzielić, ale daje tylko 1 podzadanie (< MIN_SUBTASKS) -> fail-closed.
        task_thinker.ask_model = _atrapa(_json_z_podzadaniami(1))
        decyzja_malo = task_decomposer.decide(TASK)
        checks.append(("Guard: <MIN_SUBTASKS podzadań -> should_split=False", decyzja_malo["should_split"] is False))

        # 4. Guard: model proponuje więcej niż MAX_SUBTASKS -> przycięcie, nie odmowa.
        task_thinker.ask_model = _atrapa(_json_z_podzadaniami(9))
        decyzja_duzo = task_decomposer.decide(TASK)
        checks.append(("Guard: >MAX_SUBTASKS -> przycięte do MAX_SUBTASKS, split zostaje True",
                       decyzja_duzo["should_split"] is True and len(decyzja_duzo["subtasks"]) == task_decomposer.MAX_SUBTASKS))

        # 5. Error case: odpowiedź modelu to śmieci (nie JSON) -> should_split=False.
        task_thinker.ask_model = _atrapa("Przepraszam, nie rozumiem zadania.")
        decyzja_smiec = task_decomposer.decide(TASK)
        checks.append(("Error: nieparsowalna odpowiedź -> should_split=False", decyzja_smiec["should_split"] is False))
        checks.append(("Error: nieparsowalna odpowiedź -> koszt i tak policzony", decyzja_smiec["cost_usd"] > 0))

        # 6. Error case: model niedostępny -> should_split=False, koszt 0.0, brak wyjątku.
        task_thinker.ask_model = _atrapa(None, available=False)
        decyzja_brak = task_decomposer.decide(TASK)
        checks.append(("Error: model niedostępny -> should_split=False", decyzja_brak["should_split"] is False))
        checks.append(("Error: model niedostępny -> koszt 0.0", decyzja_brak["cost_usd"] == 0.0))

        # 7. decompose(): tworzy PRAWDZIWE podzadania (subtask_of, order kolejny),
        #    w tym samym projekcie co rodzic, przypisane do "bot".
        client = _FakeClient()
        task_thinker.ask_model = _atrapa(_json_z_podzadaniami(3))
        decyzja_ok = task_decomposer.decide(TASK)
        wynik = task_decomposer.decompose(client, TASK, decyzja_ok)
        checks.append(("decompose: utworzono 3 zadania", len(client.created) == 3))
        checks.append(("decompose: subtask_of = id rodzica",
                       all(c["subtask_of"] == "T-DUZE" for c in client.created)))
        checks.append(("decompose: order kolejny od 0", [c["order"] for c in client.created] == [0, 1, 2]))
        checks.append(("decompose: project_id odziedziczony z rodzica",
                       all(c["project_id"] == "PROJ-1" for c in client.created)))
        checks.append(("decompose: assigned_to='bot' (self, nie człowiek)",
                       all(c["assigned_to"] == "bot" for c in client.created)))
        checks.append(("decompose: comment wymienia utworzone ID",
                       all(c["task_id"] in wynik["comment"] for c in client.created)))
        checks.append(("decompose: created_ids zwrócone", wynik["created_ids"] == [c["task_id"] for c in client.created]))
    finally:
        task_thinker.ask_model = original_ask_model

    print("\n--- Wynik testu dymnego task_decomposer ---")
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
