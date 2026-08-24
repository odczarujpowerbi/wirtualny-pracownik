"""
Test dymny output_decider.py. Zero sieci — task_thinker.ask_model jest
podmieniany atrapą zwracającą z góry ustaloną odpowiedź (albo śmieci, albo
brak dostępności), żeby sprawdzić parsowanie/walidację/fail-closed bez
prawdziwego wywołania modelu.

Użycie:
    python output_decider_smoke_test.py
"""

import sys
import tempfile
from pathlib import Path

import output_decider
import task_thinker

TASK = {"task_id": "T-OUT", "title": "Zestawienie kampanii MailerLite"}
TABLE_ROWS = [
    {"id": "111", "nazwa": "Newsletter 33", "odbiorcy": 2400},
    {"id": "222", "nazwa": "Webinar", "odbiorcy": 2380},
]


def _atrapa(text, available=True, source="claude_code"):
    return lambda prompt, caller=None: {"available": available, "text": text,
                                        "source": source, "detail": "OK"}


def run():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    checks = []
    original_ask_model = task_thinker.ask_model

    try:
        # 1. Happy path: model wybiera xlsx, dane tabelaryczne dostępne.
        task_thinker.ask_model = _atrapa('{"format": "xlsx", "reasoning": "Dane liczbowe."}')
        decyzja = output_decider.decide(TASK, "done", "Zrobione.",
                                        {"acceptance_notes": "Wynik.", "table_rows": TABLE_ROWS})
        checks.append(("Happy path: model wybiera xlsx, jest respektowane", decyzja["format"] == "xlsx"))
        checks.append(("Happy path: koszt policzony (claude_code proxy > 0)", decyzja["cost_usd"] > 0))

        # 2. Happy path: model wybiera pdf, dane tabelaryczne dostępne -> tabela W dokumencie.
        task_thinker.ask_model = _atrapa('{"format": "pdf", "reasoning": "Do wysłania."}')
        decyzja_pdf = output_decider.decide(TASK, "done", "Zrobione.",
                                            {"acceptance_notes": "Wynik.", "table_rows": TABLE_ROWS})
        checks.append(("Happy path: model wybiera pdf", decyzja_pdf["format"] == "pdf"))

        # 3. Guard wykonalności: model chce xlsx, ale brak danych tabelarycznych -> wymuszony pdf.
        task_thinker.ask_model = _atrapa('{"format": "xlsx", "reasoning": "..."}')
        decyzja_guard = output_decider.decide(TASK, "done", "Zrobione.", {"acceptance_notes": "Wynik."})
        checks.append(("Guard: xlsx bez table_rows -> wymuszony pdf", decyzja_guard["format"] == "pdf"))

        # 4. Error case: odpowiedź modelu to śmieci (nie JSON) -> domyślnie pdf, koszt policzony.
        task_thinker.ask_model = _atrapa("Przepraszam, nie rozumiem zadania.")
        decyzja_smiec = output_decider.decide(TASK, "done", "Zrobione.", {"acceptance_notes": "Wynik."})
        checks.append(("Error: nieparsowalna odpowiedź -> domyślnie pdf", decyzja_smiec["format"] == "pdf"))
        checks.append(("Error: nieparsowalna odpowiedź -> koszt i tak policzony", decyzja_smiec["cost_usd"] > 0))

        # 5. Error case: model niedostępny -> domyślnie pdf, koszt 0.0, brak wyjątku.
        task_thinker.ask_model = _atrapa(None, available=False)
        decyzja_brak = output_decider.decide(TASK, "done", "Zrobione.", {"acceptance_notes": "Wynik."})
        checks.append(("Error: model niedostępny -> domyślnie pdf", decyzja_brak["format"] == "pdf"))
        checks.append(("Error: model niedostępny -> koszt 0.0", decyzja_brak["cost_usd"] == 0.0))

        # 6. build_file: xlsx tworzy wynik.xlsx (niepusty), pdf z tabelą tworzy wynik.pdf (niepusty).
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            xlsx_path = output_decider.build_file(TASK, {"format": "xlsx"}, "Wynik.", TABLE_ROWS, tmp)
            checks.append(("build_file: xlsx -> wynik.xlsx niepusty",
                           xlsx_path.name == "wynik.xlsx" and xlsx_path.stat().st_size > 0))
            checks.append(("build_file: xlsx -> brak wynik.pdf obok", not (tmp / "wynik.pdf").exists()))

            pdf_path = output_decider.build_file(TASK, {"format": "pdf"}, "Wynik.", TABLE_ROWS, tmp)
            checks.append(("build_file: pdf z tabelą -> wynik.pdf niepusty",
                           pdf_path.name == "wynik.pdf" and pdf_path.stat().st_size > 0))

            md_path = output_decider.build_file(TASK, {"format": "md"}, "Sam tekst, bez tabeli.", None, tmp)
            md_text = md_path.read_text(encoding="utf-8")
            checks.append(("build_file: md bez table_rows -> brak sekcji 'Dane'", "## Dane" not in md_text))
            checks.append(("build_file: md -> treść to acceptance_notes", "Sam tekst, bez tabeli." in md_text))
    finally:
        task_thinker.ask_model = original_ask_model

    print("\n--- Wynik testu dymnego output_decider ---")
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
