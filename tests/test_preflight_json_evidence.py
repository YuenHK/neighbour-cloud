import json

import pytest

from tools.acceptance_preflight import collect, read_object


@pytest.mark.parametrize('raw', [
    b'{"passed":false,"passed":true}',
    b'{"checks":{"health":false,"health":true}}',
    b'{"passed":false,"pass\\u0065d":true}',
    b'{"metadata":[{"private":"one","private":"two"}]}',
    b'{"metadata":NaN}', b'{"metadata":Infinity}', b'{"metadata":-Infinity}',
    b'{"metadata":1e999}', b'{"metadata":-1e999}',
])
def test_ambiguous_or_nonstandard_json_is_unusable_without_changing_file(tmp_path, raw):
    path = tmp_path / 'evidence.json'
    path.write_bytes(raw)
    assert read_object(path) is None
    assert path.read_bytes() == raw


def test_standard_bom_unicode_nested_evidence_remains_readable(tmp_path):
    path = tmp_path / 'evidence.json'
    value = {'passed': True, 'checks': {'health': True},
             'metadata': [{'name': '中文', 'nullable': None, 'values': [1, .25, False]}]}
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8-sig')
    assert read_object(path) == value


def test_invalid_saved_evidence_cannot_become_claimed_pass_or_registered_bridge(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    backend = runtime / 'backend-acceptance.json'
    registry = runtime / 'airi-processes.json'
    raw_backend = b'{"passed":false,"passed":true,"checks":{"health":true}}'
    raw_registry = b'{"bridge":0,"bridge":123,"private":"do-not-echo"}'
    backend.write_bytes(raw_backend)
    registry.write_bytes(raw_registry)
    report = collect(tmp_path, offline=True)
    assert report['saved_backend_report']['claims_passed'] is False
    assert report['saved_backend_report']['reported_identity_matches_copied_files'] is False
    assert report['bridge']['registry_status'] == 'missing_or_invalid'
    assert report['bridge']['delivery_verified'] is False
    assert report['complete_system_accepted'] is False
    assert 'do-not-echo' not in json.dumps(report)
    assert backend.read_bytes() == raw_backend
    assert registry.read_bytes() == raw_registry
