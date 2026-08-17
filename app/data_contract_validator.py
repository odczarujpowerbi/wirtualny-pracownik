"""
Waliduje plik źródłowy wobec UZGODNIONEGO kontraktu struktury (per
klient/proces) — `config/data_contracts/*.yaml` (PLAN-WDROZENIA.md sekcja
10, SKRYPTY.md kategoria M).

Różnica względem `source_schema_watcher.py`: watcher pyta "czy coś się
zmieniło od ostatniego razu" (porównanie z automatycznie zapisanym
baseline'em, bez wiedzy co jest 'poprawne'). Ten moduł pyta "czy plik
spełnia to, na co się umówiliśmy" (porównanie ze świadomie zadeklarowanym
kontraktem). Uzupełniają się: watcher wykrywa KAŻDĄ zmianę i tworzy zadanie
do potwierdzenia; kontrakt daje twarde kryterium akceptacji, które można
wpiąć jako bramkę PRZED odświeżeniem/przepięciem, nie tylko jako alert po
fakcie.

Reużywa parser struktury z `source_schema_watcher.py`, żeby nie mieć dwóch
niezależnych implementacji odczytu CSV, które mogłyby zacząć się różnić.
"""

from pathlib import Path

import yaml

from source_schema_watcher import read_csv_schema

CONTRACTS_DIR = Path(__file__).parent / "config" / "data_contracts"


def load_contract(name, contracts_dir=CONTRACTS_DIR):
    path = contracts_dir / f"{name}.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def validate_against_contract(file_path, contract):
    snapshot = read_csv_schema(file_path)
    columns = set(snapshot["columns"])
    required = set(contract.get("required_columns", []))
    optional = set(contract.get("optional_columns", []))
    declared_types = contract.get("types", {})
    strict = contract.get("strict", False)

    errors, warnings = [], []

    missing = sorted(required - columns)
    if missing:
        errors.append(f"Brakuje wymaganych kolumn: {', '.join(missing)}")

    unexpected = sorted(columns - required - optional)
    if unexpected:
        message = f"Kolumny spoza kontraktu: {', '.join(unexpected)}"
        (errors if strict else warnings).append(message)

    for col, expected_type in declared_types.items():
        actual_type = snapshot["types"].get(col)
        if actual_type is None:
            continue  # kolumna w ogóle nie istnieje — już zgłoszone wyżej jako brak
        if actual_type != "unknown" and actual_type != expected_type:
            errors.append(f"Kolumna '{col}': oczekiwany typ {expected_type}, wykryto {actual_type}")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "row_count": snapshot["row_count"],
    }


def validate_file(file_path, contract_name, contracts_dir=CONTRACTS_DIR):
    contract = load_contract(contract_name, contracts_dir)
    return validate_against_contract(file_path, contract)


if __name__ == "__main__":
    import sys

    base = Path(__file__).parent / "mock_data"
    if len(sys.argv) == 3:
        result = validate_file(sys.argv[1], sys.argv[2])
        print(result)
    else:
        print("Bez argumentów — demo na przykładowych plikach (v1 zgodny, v2 ze zmienioną strukturą):\n")
        print("v1 (powinno być valid=True): ", validate_file(base / "source_sample_v1.csv", "indeka_sample"))
        print("v2 (powinno być valid=False):", validate_file(base / "source_sample_v2_changed.csv", "indeka_sample"))
