"""
Rejestr i egzekutor kontraktów narzędzi (M1 — przeplyw.html sekcja 5). Jedno
miejsce, które odpowiada na pytanie: "czy TO narzędzie z TYMI parametrami wolno
uruchomić?". Fundament zasady autora: model nie dostaje dowolnego shell, tylko
narzędzia zarejestrowane w config/tool_contracts.yaml.

check_call(tool, params) -> {allowed: bool, reason: str, risk: str}:
  - narzędzie spoza rejestru -> odmowa (fail-closed),
  - brak wymaganego parametru -> odmowa,
  - parametr type=path poza allowed_roots -> odmowa,
Każda odmowa niesie czytelny powód (trafia do audytu i eskalacji).
"""

from pathlib import Path

import yaml

APP_DIR = Path(__file__).parent
CONTRACTS_PATH = APP_DIR / "config" / "tool_contracts.yaml"


def load_contracts(path=CONTRACTS_PATH):
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("tools", {})


def get_contract(tool, path=CONTRACTS_PATH):
    return load_contracts(path).get(tool)


def _resolve_roots(contract):
    """allowed_roots z kontraktu -> bezwzględne ścieżki (względem app/)."""
    return [(APP_DIR / r).resolve() for r in contract.get("allowed_roots", [])]


def _path_within(path, roots):
    resolved = Path(path).resolve()
    return any(resolved == root or root in resolved.parents for root in roots)


def _allow(risk):
    return {"allowed": True, "reason": "", "risk": risk}


def _deny(reason, risk="red"):
    return {"allowed": False, "reason": reason, "risk": risk}


def check_call(tool, params, path=CONTRACTS_PATH):
    """Sprawdza pojedyncze wywołanie narzędzia wobec jego kontraktu."""
    contract = get_contract(tool, path)
    if contract is None:
        return _deny(f"Narzędzie '{tool}' nie jest w rejestrze kontraktów — odmowa (fail-closed).")

    risk = contract.get("risk", "red")
    roots = _resolve_roots(contract)
    params = params or {}

    for name, spec in (contract.get("params") or {}).items():
        spec = spec or {}
        value = params.get(name)
        if spec.get("required") and (value is None or value == ""):
            return _deny(f"Brak wymaganego parametru '{name}' dla narzędzia '{tool}'.", risk)
        if value in (None, ""):
            continue
        if spec.get("type") == "path":
            if not roots:
                return _deny(f"Narzędzie '{tool}' nie ma zadeklarowanych allowed_roots dla parametru ścieżki.", risk)
            if not _path_within(value, roots):
                return _deny(
                    f"Ścieżka '{value}' (parametr '{name}') jest poza allowed_roots narzędzia '{tool}' "
                    f"— odmowa (fail-closed).", risk)

    return _allow(risk)


if __name__ == "__main__":
    import json
    import sys

    tool = sys.argv[1] if len(sys.argv) > 1 else "validate_pbip"
    params = {"project_path": sys.argv[2]} if len(sys.argv) > 2 else {}
    print(json.dumps(check_call(tool, params), ensure_ascii=False, indent=2))
