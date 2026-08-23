"""
Generyczny silnik budowy raportów spoza Power BI (Excel/Google
Sheets/dokument) wg zadeklarowanego rezultatu — PLAN-WDROZENIA.md sekcja
10, SKRYPTY.md kategoria M ("Kadry, Finansowy, Dane ruchy mag, raport na
stronę" — dziś robione ręcznie przez Asię).

Zasada z sekcji 12 planu: to jest silnik (przyjmuje gotowe rekordy,
formatuje wynik), nie źródło prawdy o KONKRETNYM raporcie firmowym —
podłączenie realnych danych (np. z CRM, z systemu kadrowego) to osobny
krok integracyjny, nie część tego modułu.

Markdown i CSV działają na bibliotece standardowej. XLSX używa `openpyxl`
(requirements.txt) — import LENIWY (wewnątrz write_xlsx_report), żeby import
tego modułu nie wymagał pakietu, gdy nikt xlsx nie potrzebuje.

Akcja `report_build` jest już `yellow` w approval_policy.yaml — wynik
raportu przechodzi normalną ścieżkę walidacji/auto-zatwierdzenia z sekcji 3
planu, zanim trafi do klienta.
"""

import csv
import re


def build_markdown_table(rows, columns=None):
    if not rows:
        return "_(brak danych)_"
    columns = columns or list(rows[0].keys())

    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |")
    return "\n".join(lines)


def write_csv_report(rows, output_path, columns=None):
    columns = columns or (list(rows[0].keys()) if rows else [])
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return output_path


_XLSX_SHEET_TITLE_INVALID = re.compile(r"[\\/*?:\[\]]")


def _xlsx_sheet_title(title):
    """Nazwa arkusza Excela: max 31 znaków, bez \\ / * ? : [ ] (openpyxl rzuca
    ValueError na te znaki, nie tylko na długość — sam `title[:31]` nie wystarczy)."""
    sanitized = _XLSX_SHEET_TITLE_INVALID.sub(" ", title).strip()
    return sanitized[:31] or "Raport"


def write_xlsx_report(title, rows, output_path, columns=None):
    import openpyxl

    columns = columns or (list(rows[0].keys()) if rows else [])
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = _xlsx_sheet_title(title)
    sheet.append(columns)
    for row in rows:
        sheet.append([row.get(c, "") for c in columns])
    for cell in sheet[1]:
        cell.font = openpyxl.styles.Font(bold=True)
    workbook.save(output_path)
    return output_path


def build_report(title, rows, columns=None, output_format="markdown", output_path=None):
    if output_format == "markdown":
        return f"# {title}\n\n{build_markdown_table(rows, columns)}"

    if output_format == "csv":
        if not output_path:
            raise ValueError("output_format='csv' wymaga output_path.")
        return write_csv_report(rows, output_path, columns)

    if output_format == "xlsx":
        if not output_path:
            raise ValueError("output_format='xlsx' wymaga output_path.")
        return write_xlsx_report(title, rows, output_path, columns)

    raise ValueError(f"Nieznany output_format: {output_format!r} (obsługiwane: markdown, csv, xlsx)")


def run_report_task(client, task_id, title, rows, columns=None):
    """Buduje raport markdown i publikuje go jako komentarz w Projectly —
    droga akceptacji dla `report_build` (yellow) jest już w approval_policy.yaml,
    ten skrypt tylko produkuje treść."""
    text = build_report(title, rows, columns=columns, output_format="markdown")
    client.post_comment(task_id, text)
    return text


if __name__ == "__main__":
    demo_rows = [
        {"Pracownik": "Asia", "Godziny_zaplanowane": 160, "Godziny_zrealizowane": 172},
        {"Pracownik": "Kacper", "Godziny_zaplanowane": 160, "Godziny_zrealizowane": 168},
        {"Pracownik": "Aldona", "Godziny_zaplanowane": 120, "Godziny_zrealizowane": 131},
    ]
    print(build_report("Raport Kadry — sierpień 2026", demo_rows))
