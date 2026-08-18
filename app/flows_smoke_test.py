"""
Test dymny M2b (przepływy agentów + trwała historia decyzji). Pokrywa:
- log_decision -> get_recent_decisions (i to, że zdarzenia techniczne z agent=NULL
  NIE zaśmiecają przepływu),
- executor.execute na realnym przykładzie PBIP (przechodzi) oraz odmowę ścieżki
  spoza dozwolonego katalogu (fail-closed),
- export_decisions.export do JSONL.

Używa TYMCZASOWEJ bazy (podmiana state_store.DB_PATH), żeby nie dotykać żywego
runs/state.db. Wpina się automatycznie w self_check.py (glob *_smoke_test.py).
"""

import tempfile
from pathlib import Path

import state_store

NOW = "2026-08-18T10:00:00+00:00"


def _use_temp_db():
    tmp = Path(tempfile.mkdtemp()) / "test_state.db"
    state_store.DB_PATH = tmp
    return tmp


def test_log_decision_roundtrip():
    _use_temp_db()
    state_store.log_decision("T-1", agent="pawel", decision="risk=green",
                             reason="odczyt bez efektu", now=NOW, model="opus-4-8", cost_usd=0.0)
    # zdarzenie techniczne (agent NULL) NIE powinno trafić do przepływu
    state_store.record_event("T-1", "thinking", "szczegół techniczny", NOW)

    decisions = state_store.get_recent_decisions()
    assert len(decisions) == 1, f"oczekiwano 1 decyzji (bez zdarzeń technicznych), jest {len(decisions)}"
    d = decisions[0]
    assert d["agent"] == "pawel", d
    assert d["decision"] == "risk=green", d
    assert d["reason"] == "odczyt bez efektu", d
    assert d["model"] == "opus-4-8", d
    print("OK  log_decision -> get_recent_decisions (pomija zdarzenia techniczne)")


def test_executor_pbip_real():
    import executor
    result = executor.execute({"action": "validate_pbip", "project_path": "mock_data/sample_pbip"})
    assert result is not None, "executor powinien obsłużyć validate_pbip"
    assert result["executed"] is True, result
    assert result["output"]["errors"] == [], result  # realna walidacja: brak błędów struktury
    checks = result["functional_checks"]  # kontrakt dla Franka: LISTA checków, nie dict
    assert isinstance(checks, list) and checks[0]["type"] == "pbip_valid", checks
    print("OK  executor.execute — realna walidacja PBIP przeszła")


def test_executor_refuses_outside_workspace():
    import executor
    result = executor.execute({"action": "validate_pbip", "project_path": "C:/Windows"})
    assert result is not None, "odmowa też jest wynikiem, nie None"
    assert result["executed"] is False, "ścieżka poza workspace musi być odrzucona (fail-closed)"
    print("OK  executor odmawia ścieżki spoza dozwolonego katalogu")


def test_export_decisions():
    _use_temp_db()
    state_store.log_decision("T-9", agent="gustaw", decision="gate_passed", reason="wszystko ok", now=NOW)
    import export_decisions
    out = Path(tempfile.mkdtemp()) / "dec.jsonl"
    res = export_decisions.export(fmt="jsonl", out=str(out))
    assert res["count"] == 1, res
    assert out.exists(), "plik eksportu nie powstał"
    assert "gate_passed" in out.read_text(encoding="utf-8"), "brak decyzji w eksporcie"
    print("OK  export_decisions zapisał JSONL")


if __name__ == "__main__":
    test_log_decision_roundtrip()
    test_executor_pbip_real()
    test_executor_refuses_outside_workspace()
    test_export_decisions()
    print("\nWszystkie testy M2b przeszły.")
