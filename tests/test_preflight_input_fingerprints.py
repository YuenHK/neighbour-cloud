import hashlib
import io
import json

import pytest

from tools import acceptance_preflight as preflight


def test_hash_is_of_exact_single_read_including_bom():
    raw = b'\xef\xbb\xbf{ "bridge": 0 }\n'

    class Once:
        calls = 0

        def open(self, mode):
            assert mode == 'rb'
            self.calls += 1
            assert self.calls == 1
            return io.BytesIO(raw)

    source = Once()
    value, evidence = preflight.read_object_evidence(source, 'explicit')
    assert value == {'bridge': 0}
    assert evidence['sha256'] == hashlib.sha256(raw).hexdigest()
    assert evidence['byte_count'] == len(raw)
    assert evidence['state'] == 'parsed_object'
    assert source.calls == 1


@pytest.mark.parametrize('raw', [b'[]', b'{', b'{"a":1,"a":2}', b'{"a":NaN}',
                                  b'{"a":1e999}', b'\xff', b' ' * (128 * 1024 + 1)],
                         ids=['array', 'syntax', 'duplicate', 'nan', 'overflow', 'encoding', 'oversize'])
def test_invalid_inputs_never_have_success_fingerprint(tmp_path, raw):
    source = tmp_path / 'private-name.json'
    source.write_bytes(raw)
    value, evidence = preflight.read_object_evidence(source, 'explicit')
    assert value is None
    assert evidence['sha256'] is None
    assert evidence['byte_count'] is None
    assert evidence['state'] == ('too_large' if len(raw) > 128 * 1024 else 'invalid_object')
    assert 'private-name' not in json.dumps(evidence)
    assert preflight.read_object(source) is None


def test_missing_and_unsupplied_are_distinct(tmp_path):
    assert preflight.read_object_evidence(tmp_path / 'missing', 'explicit')[1]['state'] == 'unreadable'
    value, evidence = preflight.read_object_evidence(None, 'not_supplied')
    assert value is None
    assert evidence['state'] == 'not_supplied'
    assert evidence['sha256'] is None


def test_collect_tracks_selection_and_changed_bytes_without_acceptance(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    registry = runtime / 'airi-processes.json'
    registry.write_text('{"bridge":0}', encoding='utf-8')
    selected = runtime / 'private-selected.json'
    selected.write_text('{"secret":"never echo"}', encoding='utf-8')
    first = preflight.collect(tmp_path, offline=True)
    assert first['evidence_inputs']['backend']['selection'] == 'legacy_default'
    assert first['evidence_inputs']['registry']['selection'] == 'fixed_registry'
    for name in ('sdk', 'control'):
        assert first['evidence_inputs'][name]['state'] == 'not_supplied'
    second = preflight.collect(tmp_path, offline=True, backend_report=selected,
                               sdk_report=selected, control_report=selected)
    for name in ('backend', 'sdk', 'control'):
        assert second['evidence_inputs'][name]['selection'] == 'explicit'
        assert second['evidence_inputs'][name]['sha256'] == hashlib.sha256(selected.read_bytes()).hexdigest()
    selected.write_text('{"secret":"changed"}', encoding='utf-8')
    third = preflight.collect(tmp_path, offline=True, backend_report=selected)
    assert third['evidence_inputs']['backend']['sha256'] != second['evidence_inputs']['backend']['sha256']
    for report in (first, second, third):
        assert report['complete_system_accepted'] is False
        assert report['hardware_acceptance'] is False
        assert report['gates']['bridge_delivery'] is False
        assert report['gates']['sdk_install_import'] is False
        assert 'never echo' not in json.dumps(report)
        assert 'private-selected' not in json.dumps(report)
