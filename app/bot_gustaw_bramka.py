"""
Gustaw — bramka jakości (orkiestrator).

Funkcja: przepuszcza zadanie po kolei przez wszystkich botów walidujących
(Bartek, Franek, Oskar, Bożena), zbiera ich werdykty i podejmuje JEDNĄ decyzję:
czy efekt może iść do człowieka jako gotowy, czy trzeba go eskalować z zebranymi
zastrzeżeniami. To jest ta "seria testów, zanim człowiek dostanie odpowiedź".

Konfiguracja: config/validation_gate.yaml (kolejność botów, którzy są
obowiązkowi, ile zgód wymagane, które problemy blokują). Edytowalne bez zmiany
kodu.

Decyzja `passed` (zadanie przechodzi bramkę) wymaga JEDNOCZEŚNIE:
  - brak blokującego odrzucenia (żaden bot nie zwrócił 'rejected'),
  - wszystkie boty OBOWIĄZKOWE zatwierdziły (mandatory),
  - liczba zatwierdzeń >= required_approvals.
Inaczej: zadanie NIE przechodzi -> eskalacja do człowieka z listą zastrzeżeń.

Dodatkowo Gustaw robi deterministyczną kontrolę zakresu kosztu PRZED botami
(max_ai_cost_usd z zadania) — przekroczenie budżetu blokuje od razu, bez
angażowania modeli.

Kontrakt bramki:
    run_gate(task, execution_result, config=None) -> dict z polami:
        passed, verdicts, approvals, required, mandatory_ok, concerns, summary
"""

from pathlib import Path

import yaml

import bot_bartek_dubler
import bot_bozena_biznes
import bot_franek_funkcjonalny
import bot_oskar_wizja
from bot_common import verdict

GATE_CONFIG_PATH = Path(__file__).parent / "config" / "validation_gate.yaml"

REGISTRY = {
    "bartek": bot_bartek_dubler.review,
    "franek": bot_franek_funkcjonalny.review,
    "oskar": bot_oskar_wizja.review,
    "bozena": bot_bozena_biznes.review,
}


def load_gate_config(path=GATE_CONFIG_PATH):
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _scope_guard(task, execution_result):
    """Deterministyczna bramka kosztu przed botami. Zwraca werdykt 'rejected'
    przy przekroczeniu budżetu, inaczej None (idziemy dalej)."""
    max_cost = task.get("max_ai_cost_usd")
    actual = execution_result.get("cost_usd", 0) or 0
    if max_cost is not None and actual > max_cost:
        return verdict(
            "zakres", "rejected", 1.0,
            f"Koszt {actual} USD przekracza zadeklarowany limit {max_cost} USD.",
            concerns=[f"Przekroczony budżet zadania: {actual} > {max_cost} USD."],
        )
    return None


def run_gate(task, execution_result, config=None):
    cfg = config or load_gate_config()
    gate = cfg.get("gate", {})
    bots_cfg = cfg.get("bots", {})

    if not gate.get("enabled", True):
        return {"passed": True, "verdicts": [], "approvals": 0, "required": 0,
                "mandatory_ok": True, "concerns": [], "summary": "Bramka wyłączona w konfiguracji."}

    verdicts = []

    scope = _scope_guard(task, execution_result)
    if scope is not None:
        verdicts.append(scope)

    for name in gate.get("order", list(REGISTRY.keys())):
        bot_cfg = bots_cfg.get(name, {})
        if not bot_cfg.get("enabled", True):
            continue
        review_fn = REGISTRY.get(name)
        if review_fn is None:
            continue
        try:
            verdicts.append(review_fn(task, execution_result, bot_cfg))
        except Exception as exc:  # noqa: BLE001 — jeden zawodny bot nie może ubić bramki
            verdicts.append(verdict(name, "rejected", 0.5, f"Bot się wywalił: {exc}",
                                    concerns=[f"Wyjątek w bocie {name}."]))

    approvals = [v for v in verdicts if v["verdict"] == "approved"]
    rejections = [v for v in verdicts if v["verdict"] == "rejected"]
    required = gate.get("required_approvals", 1)
    mandatory = gate.get("mandatory", [])
    mandatory_ok = all(
        any(v["bot"] == m and v["verdict"] == "approved" for v in verdicts) for m in mandatory
    )

    passed = (not rejections) and mandatory_ok and (len(approvals) >= required)
    concerns = [c for v in verdicts for c in v.get("concerns", [])]

    return {
        "passed": passed,
        "verdicts": verdicts,
        "approvals": len(approvals),
        "required": required,
        "mandatory_ok": mandatory_ok,
        "concerns": concerns,
        "summary": _summary(verdicts, passed, len(approvals), required, mandatory_ok),
    }


def _summary(verdicts, passed, approvals, required, mandatory_ok):
    parts = [f"{v['bot']}={v['verdict']}" for v in verdicts]
    head = "PRZESZŁO" if passed else "NIE przeszło"
    extra = "" if mandatory_ok else " (brak zgody bota obowiązkowego)"
    return f"Bramka: {head}. Zgody {approvals}/{required}{extra}. Werdykty: {', '.join(parts) or 'brak botów'}."


if __name__ == "__main__":
    demo_task = {"title": "Raport INDEKA", "action_type": "report_build",
                 "acceptance_criteria": "Kolumny zgodne, liczby ze źródła", "max_ai_cost_usd": 1.0}
    demo_exec = {"cost_usd": 0.1, "acceptance_notes": "Zbudowano raport z 3 stronami."}
    result = run_gate(demo_task, demo_exec)
    print(result["summary"])
    for v in result["verdicts"]:
        print(" -", v["bot"], v["verdict"], "|", v["detail"][:80])
