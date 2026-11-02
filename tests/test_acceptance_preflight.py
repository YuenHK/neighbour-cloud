import json

from tools.acceptance_preflight import assemble, collect


def test_copied_files_do_not_mean_live_deployment_or_accepted_models():
    report = assemble({'files': {'disk_matches_manifest': True}, 'live_identity_matches': False},
                      {'litter_model_accepted': False, 'person_privacy_accepted': False}, 0, None)
    assert report['gates']['copied_files'] is True
    assert report['gates']['live_hub_version'] is False
    assert report['ready_to_schedule_field_acceptance'] is False
    assert report['complete_system_accepted'] is False


def test_registered_bridge_and_perfect_model_flags_are_not_delivery_or_hardware_acceptance():
    report = assemble({'files': {'disk_matches_manifest': True}, 'live_identity_matches': True},
                      {'litter_model_accepted': True, 'person_privacy_accepted': True}, 123,
                      {'passed': True, 'checks': {'health': True}})
    assert report['bridge']['registry_status'] == 'registered_not_process_verified'
    assert report['bridge']['delivery_verified'] is False
    assert report['ready_to_schedule_field_acceptance'] is False
    assert report['hardware_acceptance'] is False
    assert report['saved_backend_report']['freshness_verified'] is False


def test_missing_project_evidence_is_read_only_and_never_opens_camera(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('preflight must never open camera')
    monkeypatch.setattr('cv2.VideoCapture', forbidden)
    report = collect(tmp_path, offline=True)
    assert report['gates']['copied_files'] is False
    assert report['gates']['litter_report'] is False
    assert report['bridge']['registry_status'] == 'missing_or_invalid'
    assert report['camera_opened'] is False and report['services_modified'] is False
    assert list(tmp_path.iterdir()) == []


def test_registry_and_saved_report_are_allowlisted_not_echoed(tmp_path):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    registry = runtime / 'airi-processes.json'
    registry.write_text(json.dumps({'bridge': True, 'secret': 'do-not-echo'}), encoding='utf-8')
    report = collect(tmp_path, offline=True)
    assert report['bridge']['registry_status'] == 'missing_or_invalid'
    assert 'do-not-echo' not in json.dumps(report)
    assert registry.read_text(encoding='utf-8') == json.dumps({'bridge': True, 'secret': 'do-not-echo'})


def test_invalid_camera_configuration_is_reported_without_opening_camera(tmp_path, monkeypatch):
    monkeypatch.setenv('ZHIWEI_CAMERA_INDEX', 'not-a-device-number')
    report = collect(tmp_path, offline=True)
    assert report['vision_configuration_error'] == 'ValueError'
    assert report['gates']['litter_report'] is False
    assert report['camera_opened'] is False
