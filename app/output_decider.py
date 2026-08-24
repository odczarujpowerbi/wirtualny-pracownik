"""
Agent sterujący decyduje, JAKI plik (md/docx/pdf/xlsx) najlepiej dokumentuje
wynik zadania — żadna reguła w kodzie nie wymusza formatu na podstawie źródła
zadania (MailerLite, Zanfia, PBIP, ...). Decyzja jest per zadanie, model
dostaje tylko sam wynik + informację, czy są dostępne dane tabelaryczne
(nie same dane — to podpowiedź, nie treść do przepisania).

Rozdział odpowiedzialności: `decide()` pyta model i waliduje odpowiedź,
`build_file()` buduje plik DETERMINISTYCZNIE z prawdziwej treści zadania —
model wybiera format, nigdy nie wymyśla treści dokumentu.

Fail-closed: brak modelu / nieparsowalna odpowiedź / format niewykonalny
(xlsx bez danych) -> zawsze PDF, żeby "ma powstać jakiś plik" nie zależało od
dostępności modelu (decyzja właściciela 24.08.2026).
"""

import json

import cost_estimator
import document_builder
import report_builder
import task_thinker

FORMATY = {"pdf", "docx", "md", "xlsx"}
_DOMYSLNY_FORMAT = "pdf"


def _build_prompt(task, status, comment, execution_result, table_rows):
    wynik = (execution_result or {}).get("acceptance_notes") or comment or ""
    tabela_info = ""
    if table_rows:
        kolumny = ", ".join(table_rows[0].keys())
        tabela_info = (
            f"\n\nDostępne dane tabelaryczne: {len(table_rows)} wierszy, kolumny: {kolumny}. "
            "Możesz je umieścić w arkuszu xlsx, w tabeli wewnątrz dokumentu, albo pominąć."
        )
    return (
        f"Zadanie: {task.get('title', '')}\n"
        f"Status: {status}\n"
        f"Wynik:\n{wynik[:4000]}"
        f"{tabela_info}\n\n"
        "Zdecyduj, jaki JEDEN plik najlepiej udokumentuje ten wynik dla człowieka, "
        "który go później przeczyta. Domyślnie preferuj PDF (czytelny, gotowy do wysłania "
        "dalej). Wybierz xlsx TYLKO gdy wynik to głównie dane liczbowe/tabelaryczne do dalszej "
        "analizy. Wybierz md dla krótkiej, technicznej notatki. Wybierz docx, gdy dokument ma "
        "być dalej edytowany przez człowieka.\n\n"
        "Odpowiedz WYŁĄCZNIE obiektem JSON, bez komentarza:\n"
        '{"format": "pdf"|"docx"|"md"|"xlsx", "reasoning": "<1 zdanie>"}'
    )


def _parse_decision(answer_text):
    """Wyciąga {'format':..., 'reasoning':...} z odpowiedzi (nawet gdy model
    doda tekst wokół JSON) — wzorzec bot_oskar_wizja._parse_json_verdict.
    Zwraca None, gdy nie da się sparsować albo format jest nieznany."""
    start, end = answer_text.find("{"), answer_text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(answer_text[start:end + 1])
    except ValueError:
        return None
    format_ = str(data.get("format", "")).strip().lower()
    if format_ not in FORMATY:
        return None
    return {"format": format_, "reasoning": str(data.get("reasoning") or "").strip()}


def decide(task, status, comment, execution_result=None):
    """Pyta model, jaki format pliku wybrać dla wyniku tego zadania. Zwraca
    {"format", "reasoning", "cost_usd", "source"}. Nigdy nie rzuca — brak
    modelu / odpowiedź nie do sparsowania / format niewykonalny (xlsx bez
    danych) degradują do PDF, cost_usd=0.0."""
    table_rows = (execution_result or {}).get("table_rows")
    prompt = _build_prompt(task, status, comment, execution_result, table_rows)

    odpowiedz = task_thinker.ask_model(prompt, caller="output_decider.decide")
    if not odpowiedz.get("available") or not odpowiedz.get("text"):
        return {"format": _DOMYSLNY_FORMAT, "reasoning": "Brak modelu — domyślnie PDF.",
                "cost_usd": 0.0, "source": None}

    decyzja = _parse_decision(odpowiedz["text"])
    cost_usd = cost_estimator.estimate_call(
        odpowiedz.get("source") or "claude_code",
        input_chars=len(prompt), output_chars=len(odpowiedz["text"]))
    if decyzja is None:
        return {"format": _DOMYSLNY_FORMAT, "reasoning": "Odpowiedź modelu nieparsowalna — domyślnie PDF.",
                "cost_usd": cost_usd, "source": odpowiedz.get("source")}

    if decyzja["format"] == "xlsx" and not table_rows:
        return {"format": _DOMYSLNY_FORMAT,
                "reasoning": "Model wybrał xlsx, ale brak danych tabelarycznych — domyślnie PDF.",
                "cost_usd": cost_usd, "source": odpowiedz.get("source")}

    return {**decyzja, "cost_usd": cost_usd, "source": odpowiedz.get("source")}


def build_file(task, decision, acceptance_notes, table_rows, folder):
    """Buduje DETERMINISTYCZNIE plik `wynik.<format>` z prawdziwej treści
    zadania — model (przez `decision["format"]`) wybrał tylko format, treść
    zawsze pochodzi z `acceptance_notes`/`table_rows`, nigdy z modelu. Zwraca
    ścieżkę pliku."""
    title = task.get("title") or "Zadanie"
    format_ = decision["format"]
    # document_builder.build_* tworzą katalog nadrzędny samodzielnie (_ensure_parent),
    # report_builder.write_xlsx_report NIE — folder zadania jest nowy (jeszcze
    # nieutworzony), więc bez tego zapis xlsx do świeżego folderu wywala się.
    folder.mkdir(parents=True, exist_ok=True)

    if format_ == "xlsx":
        return report_builder.write_xlsx_report(title, table_rows, folder / "wynik.xlsx")

    sections = [{"heading": "Wynik", "text": acceptance_notes or ""}]
    if table_rows:
        sections.append({"heading": "Dane", "table": {"rows": table_rows}})

    if format_ == "docx":
        return document_builder.build_docx(title, sections, folder / "wynik.docx")
    if format_ == "md":
        return document_builder.build_md(title, sections, folder / "wynik.md")
    return document_builder.build_pdf(title, sections, folder / "wynik.pdf")
