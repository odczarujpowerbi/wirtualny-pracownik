"""
Test dymny rejestru kontraktów narzędzi (M1). Pokrywa cztery bramki fail-closed:
- narzędzie spoza rejestru -> odmowa,
- ścieżka wewnątrz allowed_roots -> zgoda,
- ścieżka poza allowed_roots -> odmowa,
- brak wymaganego parametru -> odmowa.

Czyta prawdziwy config/tool_contracts.yaml (read-only, nic nie zmienia). Wpina
się automatycznie w self_check.py.
"""

import tool_registry


def test_unknown_tool_denied():
    r = tool_registry.check_call("rm_rf_everything", {"path": "C:/"})
    assert r["allowed"] is False, "narzędzie spoza rejestru musi być odrzucone"
    assert "rejestr" in r["reason"].lower(), r
    print("OK  narzędzie spoza rejestru odrzucone (fail-closed)")


def test_allowed_path():
    r = tool_registry.check_call("validate_pbip", {"project_path": "mock_data/sample_pbip"})
    assert r["allowed"] is True, r
    assert r["risk"] == "green", r
    print("OK  ścieżka wewnątrz allowed_roots dozwolona")


def test_path_outside_roots_denied():
    r = tool_registry.check_call("validate_pbip", {"project_path": "C:/Windows"})
    assert r["allowed"] is False, "ścieżka poza allowed_roots musi być odrzucona"
    assert "allowed_roots" in r["reason"], r
    print("OK  ścieżka poza allowed_roots odrzucona (fail-closed)")


def test_missing_required_param():
    r = tool_registry.check_call("validate_pbip", {})
    assert r["allowed"] is False, "brak wymaganego parametru musi być odrzucony"
    assert "project_path" in r["reason"], r
    print("OK  brak wymaganego parametru odrzucony")


if __name__ == "__main__":
    test_unknown_tool_denied()
    test_allowed_path()
    test_path_outside_roots_denied()
    test_missing_required_param()
    print("\nWszystkie testy rejestru kontraktów przeszły.")
