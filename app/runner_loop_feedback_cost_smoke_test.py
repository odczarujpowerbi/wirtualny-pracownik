"""
Test dymny runner_loop._zapisz_feedback — koszt PER ZADANIE (cost_usd) trafia
do set_task_feedback (docs/MCP-STATUS-I-KOSZTY.md sekcja 2, 29.08.2026), żeby
master widział rozbicie kosztów per agent jako sumę jego zadań w Projectly,
nie tylko dzienny sumaryczny koszt z cost_tracker.

Zero sieci — atrapa klienta zbiera wywołania set_task_feedback.

Użycie:
    python runner_loop_feedback_cost_smoke_test.py
"""

import sys

import runner_loop


class _FakeClient:
    def __init__(self, rzuca=False):
        self.wywolania = []
        self.rzuca = rzuca

    def set_task_feedback(self, task_id, feedback=None, actual_hours=None,
                          completed_at=None, status=None, cost_usd=None):
        if self.rzuca:
            raise RuntimeError("Symulowany błąd MCP.")
        self.wywolania.append({"task_id": task_id, "feedback": feedback, "cost_usd": cost_usd})
        return True


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []

    # --- 1. Koszt realnego wykonania trafia do set_task_feedback jako cost_usd ---
    client = _FakeClient()
    execution_result = {"tool": "agentic_task", "cost_usd": 0.4321}
    ok = runner_loop._zapisz_feedback(client, "T-1", "done", execution_result, risk="yellow")
    checks.append(("_zapisz_feedback: zwraca True przy sukcesie", ok is True))
    checks.append(("_zapisz_feedback: cost_usd przekazany do set_task_feedback",
                   client.wywolania[0]["cost_usd"] == 0.4321))
    checks.append(("_zapisz_feedback: feedback nadal niesie czytelny tekst z kosztem",
                   "0.43" in client.wywolania[0]["feedback"] and "agentic_task" in client.wywolania[0]["feedback"]))

    # --- 2. Brak cost_usd w execution_result -> 0.0 przekazywane, nie None/pominięte ---
    client2 = _FakeClient()
    runner_loop._zapisz_feedback(client2, "T-2", "done", {"tool": "fetch_url"}, risk="green")
    checks.append(("_zapisz_feedback: brak cost_usd w wyniku -> 0.0 (nie None)",
                   client2.wywolania[0]["cost_usd"] == 0.0))

    # --- 3. Klient bez metody set_task_feedback (starszy mock) -> fail-soft, False ---
    class _KlientBezMetody:
        pass
    ok3 = runner_loop._zapisz_feedback(_KlientBezMetody(), "T-3", "done", {"cost_usd": 1.0}, risk="green")
    checks.append(("_zapisz_feedback: klient bez set_task_feedback -> False, bez wyjątku", ok3 is False))

    # --- 4. Błąd MCP -> fail-soft, False, bez wyjątku ---
    client4 = _FakeClient(rzuca=True)
    ok4 = runner_loop._zapisz_feedback(client4, "T-4", "done", {"cost_usd": 1.0}, risk="green")
    checks.append(("_zapisz_feedback: błąd MCP -> False, bez wyjątku (fail-soft)", ok4 is False))

    print("\n--- Wynik testu dymnego: koszt per zadanie w _zapisz_feedback ---")
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
