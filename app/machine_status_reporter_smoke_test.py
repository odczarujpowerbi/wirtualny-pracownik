"""
Test dymny machine_status_reporter.py. Zero sieci - klient Projectly to atrapa.

Kluczowy przypadek (bug znaleziony w audycie 27.08.2026, ten sam wzorzec co
juz naprawiony w repo_auto_improver/system_health_monitor/digest_generator):
run_machine_status_report() odrzucal zwracana wartosc client.publish_status()
(bool sukces/porazka) - job_scheduler zawsze widzial status=ok, nawet gdy
publikacja do Projectly realnie zawiodla. Test pilnuje, ze porazka publikacji
jest widoczna zarowno w logu (print [machine_status_reporter]), jak i w
wartosci zwracanej (pole "published").

Uzycie:
    python machine_status_reporter_smoke_test.py
"""

import contextlib
import io

import machine_status_reporter as msr


class _FakeClient:
    def __init__(self, publish_result=True):
        self.published_calls = []
        self._publish_result = publish_result

    def publish_status(self, role, payload):
        self.published_calls.append((role, payload))
        return self._publish_result


def test_successful_publish_marks_published_true_without_warning():
    client = _FakeClient(publish_result=True)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        wynik = msr.run_machine_status_report(client=client)

    assert wynik["published"] is True, "sukces publikacji musi byc widoczny jako published=True"
    assert "[machine_status_reporter]" not in buffer.getvalue(), \
        "przy sukcesie nie powinno byc ostrzezenia w logu"
    print("OK  udana publikacja -> published=True, brak ostrzezenia")


def test_failed_publish_is_visible_in_result_and_log():
    client = _FakeClient(publish_result=False)
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer):
        wynik = msr.run_machine_status_report(client=client)

    assert wynik["published"] is False, "porazka publikacji musi byc widoczna jako published=False"
    log = buffer.getvalue()
    assert "[machine_status_reporter]" in log, "porazka publikacji musi trafic do logu (widoczne dla job_scheduler)"
    assert "nie powiodla" in log
    print("OK  nieudana publikacja (publish_status()==False) -> published=False + ostrzezenie w logu")


def test_returned_dict_keeps_existing_keys_untouched():
    """Kontrakt kluczy uzywany m.in. przez live_status_publisher_smoke_test.py
    (build_machine_status()) nie moze sie zmienic - "published" to DODATKOWE
    pole, nie zamiana istniejacego ksztaltu."""
    client = _FakeClient(publish_result=True)
    status_bezposrednio = msr.build_machine_status()
    wynik = msr.run_machine_status_report(client=client)

    for klucz in status_bezposrednio:
        assert klucz in wynik, f"brakuje istniejacego pola '{klucz}' w wyniku run_machine_status_report()"
    assert set(wynik.keys()) == set(status_bezposrednio.keys()) | {"published"}
    print("OK  istniejace pola (tool_versions, ram_available_percent, ...) nietkniete, doszlo tylko 'published'")


def test_publish_status_called_with_expected_payload():
    client = _FakeClient(publish_result=True)
    wynik = msr.run_machine_status_report(client=client)

    assert len(client.published_calls) == 1
    role, payload = client.published_calls[0]
    assert role == "machine-status"
    assert "published" not in payload, \
        "'published' jest dodawane PO wyslaniu - nie moze zmienic ksztaltu payloadu do Projectly"
    assert payload["ram_available_percent"] == wynik["ram_available_percent"]
    print("OK  payload wyslany do publish_status() nie zawiera 'published' (dodane dopiero do wyniku)")


if __name__ == "__main__":
    test_successful_publish_marks_published_true_without_warning()
    test_failed_publish_is_visible_in_result_and_log()
    test_returned_dict_keeps_existing_keys_untouched()
    test_publish_status_called_with_expected_payload()
    print("\nWszystkie testy machine_status_reporter przeszly.")
