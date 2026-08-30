"""
Franek — testy funkcjonalne efektu.

Funkcja: odpala konkretne, deterministyczne testy na REALNYM efekcie zadania —
czy plik się otwiera, czy PBIP waliduje, czy JSON jest poprawny, czy liczba się
zgadza z oczekiwaną. To najbardziej "twarda" warstwa bramki: albo test przechodzi,
albo nie, bez oceny modelu.

Testy Franek bierze z execution_result['functional_checks'] (albo z pola
'functional_checks' samego zadania). Każdy wpis to słownik:
    {"name": "...", "type": "file_exists", "target": "ścieżka"}
    {"name": "...", "type": "json_valid", "target": "plik.json"}
    {"name": "...", "type": "pbip_valid", "target": "folder_projektu_pbip"}
    {"name": "...", "type": "nonempty_file", "target": "plik"}
    {"name": "...", "type": "numbers_match", "actual": 123.4, "expected": 123.0, "tolerance": 0.5}

Brak zadeklarowanych testów = `skipped` (nie ma czego uruchomić). Nieznany typ
testu = odrzucenie (fail-closed: nie udajemy, że przeszedł test, którego nie
umiemy wykonać).

Kontrakt: patrz bot_common.py.
"""

import json
from pathlib import Path

import pbip_validate
from bot_common import verdict

BOT = "franek"


def _check_file_exists(check):
    target = Path(check.get("target", ""))
    return target.is_file(), f"plik {'istnieje' if target.is_file() else 'NIE istnieje'}: {target}"


def _check_nonempty_file(check):
    target = Path(check.get("target", ""))
    if not target.is_file():
        return False, f"plik nie istnieje: {target}"
    size = target.stat().st_size
    return size > 0, f"rozmiar pliku {size} B"


def _check_json_valid(check):
    target = Path(check.get("target", ""))
    if not target.is_file():
        return False, f"plik JSON nie istnieje: {target}"
    try:
        json.loads(target.read_text(encoding="utf-8"))
        return True, "JSON poprawny"
    except (ValueError, OSError) as exc:
        return False, f"niepoprawny JSON: {exc}"


def _check_pbip_valid(check):
    target = check.get("target", "")
    result = pbip_validate.validate_pbip(target)
    errors = result.get("errors", [])
    if errors:
        return False, "PBIP niepoprawny: " + "; ".join(errors[:3])
    return True, "struktura PBIP poprawna"


def _check_numbers_match(check):
    actual = check.get("actual")
    expected = check.get("expected")
    tolerance = check.get("tolerance", 0)
    if actual is None or expected is None:
        return False, "brak wartości actual/expected do porównania"
    ok = abs(float(actual) - float(expected)) <= float(tolerance)
    return ok, f"actual={actual} vs expected={expected} (tolerancja {tolerance})"


_CHECKERS = {
    "file_exists": _check_file_exists,
    "nonempty_file": _check_nonempty_file,
    "json_valid": _check_json_valid,
    "pbip_valid": _check_pbip_valid,
    "numbers_match": _check_numbers_match,
}


def _run_check(check):
    checker = _CHECKERS.get(check.get("type"))
    if checker is None:
        return False, f"nieznany typ testu '{check.get('type')}' — nie umiem go wykonać (fail-closed)"
    try:
        return checker(check)
    except Exception as exc:  # noqa: BLE001 — błąd testu = test nieudany, nie crash bota
        return False, f"test rzucił wyjątek: {exc}"


def review(task, execution_result, config=None, context=None):
    """context (kesz projektów/etapów/wiedzy, context_cache.py): PRZYJĘTY dla
    jednolitego wywołania z bot_gustaw_bramka.run_gate, ale NIEUŻYWANY — testy
    funkcjonalne są deterministyczne (plik istnieje/JSON poprawny/liczba się
    zgadza), kontekst biznesowy niczego tu nie zmienia."""
    config = config or {}
    checks = execution_result.get("functional_checks") or task.get("functional_checks") or []

    if not checks:
        return verdict(BOT, "skipped", 0.3, "Brak zadeklarowanych testów funkcjonalnych do uruchomienia.")

    failed = []
    passed = []
    for check in checks:
        ok, detail = _run_check(check)
        label = check.get("name") or check.get("type", "test")
        (passed if ok else failed).append(f"{label}: {detail}")

    if failed:
        blocking = config.get("blocking_on_error", True)
        return verdict(
            BOT, "rejected" if blocking else "approved", 0.85,
            f"Testy funkcjonalne: {len(passed)}/{len(checks)} przeszło.",
            concerns=[f"Nieudany test — {f}" for f in failed],
        )

    return verdict(BOT, "approved", 0.9, f"Wszystkie testy funkcjonalne przeszły ({len(passed)}/{len(checks)}).")
