"""
Test dymny env_bootstrap._current_role() — czyta config/role.json niezaleznie
od projectly_client._load_role() (zeby uniknac zaleznosci cyklicznej), wiec
obie kopie musza sie zgadzac. Uzywa tymczasowych plikow, bez sieci.
Wpina sie automatycznie w self_check.py.
"""

import json
import os
import tempfile
from pathlib import Path

from env_bootstrap import _current_role


def test_current_role_reads_configured_role():
    tmp = Path(tempfile.mkdtemp()) / "role.json"
    tmp.write_text(json.dumps({"role": "marketing"}), encoding="utf-8")
    assert _current_role(tmp) == "marketing"
    print("OK  _current_role() czyta wskazana role z role.json")


def test_current_role_defaults_to_dev_when_file_missing():
    missing = Path(tempfile.mkdtemp()) / "brak-role.json"
    assert not missing.exists()
    assert _current_role(missing) == "dev"
    print("OK  brak pliku role.json -> _current_role() domyslnie 'dev' (fail-soft)")


def test_current_role_defaults_to_dev_on_corrupt_json():
    tmp = Path(tempfile.mkdtemp()) / "role.json"
    tmp.write_text("{niepoprawny json", encoding="utf-8")
    assert _current_role(tmp) == "dev"
    print("OK  uszkodzony role.json -> _current_role() domyslnie 'dev' (fail-soft)")


def test_bot_role_env_var_overrides_role_json():
    # Dodane 29.08.2026: kilka procesow (dev/checker/marketing) na jednej
    # maszynie/repo nie moga wspoldzielic jednego role.json bez wyscigu -
    # BOT_ROLE w srodowisku ma pierwszenstwo, zeby kazdy proces wystartowac
    # z osobna rola bez dotykania wspolnego pliku.
    tmp = Path(tempfile.mkdtemp()) / "role.json"
    tmp.write_text(json.dumps({"role": "dev"}), encoding="utf-8")
    original = os.environ.get("BOT_ROLE")
    os.environ["BOT_ROLE"] = "checker"
    try:
        assert _current_role(tmp) == "checker"
    finally:
        if original is None:
            os.environ.pop("BOT_ROLE", None)
        else:
            os.environ["BOT_ROLE"] = original
    print("OK  BOT_ROLE w srodowisku ma pierwszenstwo nad role.json")


def test_bot_role_env_var_absent_falls_back_to_file():
    tmp = Path(tempfile.mkdtemp()) / "role.json"
    tmp.write_text(json.dumps({"role": "marketing"}), encoding="utf-8")
    original = os.environ.pop("BOT_ROLE", None)
    try:
        assert _current_role(tmp) == "marketing"
    finally:
        if original is not None:
            os.environ["BOT_ROLE"] = original
    print("OK  brak BOT_ROLE -> zachowanie bez zmian, czyta role.json")


if __name__ == "__main__":
    test_current_role_reads_configured_role()
    test_current_role_defaults_to_dev_when_file_missing()
    test_current_role_defaults_to_dev_on_corrupt_json()
    test_bot_role_env_var_overrides_role_json()
    test_bot_role_env_var_absent_falls_back_to_file()
    print("\nWszystkie testy env_bootstrap przeszly.")
