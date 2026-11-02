import json
import sys

import pytest

from tools import acceptance_preflight as preflight

SCOPE = 'host shutdown intent only; not worker exit or hardware stop proof'


def snapshot(**changes):
    return {'mode': 'simulation', 'state': 'safe_stop', 'direction': 'stop', 'connected': False,
            'software_stop_latched': False, 'lease_active': False, 'hardware_acceptance': False,
            'shutdown_requested': True, 'control_lifecycle_scope': SCOPE, **changes}


@pytest.mark.parametrize('state', ['safe_stop', 'fault', 'manual'])
def test_control_snapshot_never_grants_current_state_or_acceptance(state):
    report = preflight.assemble({}, {}, 0, None, control=snapshot(state=state, secret='private'))
    evidence = report['saved_control_report']
    assert evidence['state'] == 'reported_snapshot'
    assert evidence['reported_state'] == state
    assert evidence['reported_shutdown_requested'] is True
    for key in ('freshness_verified', 'runtime_binding_verified', 'current_state_verified', 'hardware_acceptance'):
        assert evidence[key] is False
    assert report['complete_system_accepted'] is False
    assert report['ready_to_schedule_field_acceptance'] is False
    assert 'private' not in json.dumps(report)


@pytest.mark.parametrize('changes', [
    {'state': 'private state'}, {'direction': []}, {'connected': 0}, {'connected': True},
    {'lease_active': 'false'}, {'hardware_acceptance': True}, {'shutdown_requested': 1},
    {'control_lifecycle_scope': 'private scope'}, {'mode': 'private mode'},
])
def test_invalid_control_fields_are_not_echoed(changes):
    evidence = preflight.saved_control_evidence(snapshot(**changes))
    assert evidence['state'] == 'invalid_snapshot'
    assert evidence['reported_state'] is None
    assert 'private' not in json.dumps(evidence)


def test_legacy_missing_lifecycle_is_unknown_not_open():
    control = snapshot()
    del control['shutdown_requested']
    assert preflight.saved_control_evidence(control)['state'] == 'invalid_snapshot'
    del control['control_lifecycle_scope']
    evidence = preflight.saved_control_evidence(control)
    assert evidence['state'] == 'reported_snapshot'
    assert evidence['reported_shutdown_requested'] is None


def test_control_report_is_explicit_read_only_and_never_auto_selected(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    selected = runtime / 'robot-status.json'
    raw = json.dumps(snapshot())
    selected.write_text(raw, encoding='utf-8')
    report = preflight.collect(tmp_path, offline=True)
    assert report['control_report_supplied'] is False
    assert report['saved_control_report']['present'] is False
    report = preflight.collect(tmp_path, offline=True, control_report=selected)
    assert report['control_report_supplied'] is True
    assert report['saved_control_report']['reported_shutdown_requested'] is True
    assert selected.read_text(encoding='utf-8') == raw
    assert list(runtime.iterdir()) == [selected]


def test_cli_passes_explicit_control_report_without_acceptance(tmp_path, monkeypatch, capsys):
    selected = tmp_path / 'selected.json'
    calls = []

    def collect(root, **options):
        calls.append(options)
        return {'complete_system_accepted': False}

    monkeypatch.setattr(preflight, 'collect', collect)
    monkeypatch.setattr(sys, 'argv', ['preflight', '--offline', '--control-report', str(selected)])
    assert preflight.main() == 2
    assert calls == [{'offline': True, 'backend_report': None, 'control_report': selected}]
    assert json.loads(capsys.readouterr().out)['complete_system_accepted'] is False
