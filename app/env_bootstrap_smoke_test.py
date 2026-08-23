"""
Test dymny env_bootstrap._current_role() — czyta config/role.json niezaleznie
od projectly_client._load_role() (zeby uniknac zaleznosci cyklicznej), wiec
obie kopie musza sie zgadzac. Uzywa tymczasowych plikow, bez sieci.
Wpina sie automatycznie w self_check.py.
"""

import json
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


if __name__ == "__main__":
    test_current_role_reads_configured_role()
    test_current_role_defaults_to_dev_when_file_missing()
    test_current_role_defaults_to_dev_on_corrupt_json()
    print("\nWszystkie testy env_bootstrap przeszly.")
