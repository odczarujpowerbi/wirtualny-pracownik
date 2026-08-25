"""
Test dymny runner_loop._zaloguj_kolejke_przy_starcie() — żądanie właściciela
25.08.2026: widoczne podsumowanie kolejki zadań zaraz po starcie bota, tylko
RAZ per proces (nie na każdym z kolejnych 30-sekundowych przebiegów).

Użycie:
    python runner_loop_startup_queue_smoke_test.py
"""

import contextlib
import io
import sys

import runner_loop


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_flag = runner_loop._zalogowano_kolejke_przy_starcie

    try:
        # --- 1. Pierwsze wywołanie w procesie: loguje liczbę i tytuły zadań ---
        runner_loop._zalogowano_kolejke_przy_starcie = False
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            runner_loop._zaloguj_kolejke_przy_starcie([{"title": "Zadanie A"}, {"title": "Zadanie B"}])
        wyjscie = buf.getvalue()
        checks.append(("Pierwsze wywołanie: loguje liczbę zadań", "kolejka zadań: 2" in wyjscie))
        checks.append(("Pierwsze wywołanie: loguje tytuły", "Zadanie A" in wyjscie and "Zadanie B" in wyjscie))

        # --- 2. Drugie wywołanie w TYM SAMYM procesie: nic nie loguje ---
        buf2 = io.StringIO()
        with contextlib.redirect_stdout(buf2):
            runner_loop._zaloguj_kolejke_przy_starcie([{"title": "Zadanie C"}])
        checks.append(("Drugie wywołanie w tym procesie: NIC nie loguje (raz na proces)", buf2.getvalue() == ""))

        # --- 3. Pusta kolejka -> komunikat 'pusto', nie wyjątek ---
        runner_loop._zalogowano_kolejke_przy_starcie = False
        buf3 = io.StringIO()
        with contextlib.redirect_stdout(buf3):
            runner_loop._zaloguj_kolejke_przy_starcie([])
        checks.append(("Pusta kolejka -> komunikat 'pusto'", "pusto" in buf3.getvalue()))

        # --- 4. Więcej niż 10 zadań -> obcina listę tytułów, dopisuje ile więcej ---
        runner_loop._zalogowano_kolejke_przy_starcie = False
        wiele = [{"title": f"Zadanie {i}"} for i in range(15)]
        buf4 = io.StringIO()
        with contextlib.redirect_stdout(buf4):
            runner_loop._zaloguj_kolejke_przy_starcie(wiele)
        wyjscie4 = buf4.getvalue()
        checks.append(("15 zadań: loguje prawdziwą liczbę (15), nie obciętą", "kolejka zadań: 15" in wyjscie4))
        checks.append(("15 zadań: dopisuje '+5 więcej'", "+5 więcej" in wyjscie4))

        # --- 5. Zadanie bez tytułu nie wywala funkcji ---
        runner_loop._zalogowano_kolejke_przy_starcie = False
        buf5 = io.StringIO()
        with contextlib.redirect_stdout(buf5):
            runner_loop._zaloguj_kolejke_przy_starcie([{}])
        checks.append(("Zadanie bez pola 'title' -> nie wywala się", "kolejka zadań: 1" in buf5.getvalue()))
    finally:
        runner_loop._zalogowano_kolejke_przy_starcie = original_flag

    print("\n--- Wynik testu dymnego runner_loop (kolejka przy starcie) ---")
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
