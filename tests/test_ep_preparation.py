"""Offline EP preparation: no SDK installation, network discovery or devices."""
import io
import json
import re
import wave

import numpy as np
import pytest
from fastapi.testclient import TestClient

from edge_hub import app as hub
from edge_hub.ep_preparation import EpVideoInbox, preparation_status, prepare_ep_tts_wav


def make_wav(rate=22050, channels=1, width=2, frames=2205):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b'\0' * frames * channels * width)
    return output.getvalue()


@pytest.mark.parametrize('rate', [16000, 22050, 24000, 48000])
def test_tts_converts_in_memory_to_ep_mono_pcm16_48khz(rate):
    result = prepare_ep_tts_wav(make_wav(rate=rate, frames=rate // 10))
    with wave.open(io.BytesIO(result)) as audio:
        assert audio.getparams()[:4] == (1, 2, 48000, 4800)
        assert len(audio.readframes(4800)) == 9600


@pytest.mark.parametrize('payload', [
    b'', b'not audio', b'x' * 1_000_001,
    make_wav(channels=2), make_wav(width=1), make_wav(rate=96000),
    make_wav(frames=0), make_wav(frames=220501), make_wav()[:-2],
], ids=['empty', 'not-wav', 'too-large', 'stereo', 'pcm8', 'unsupported-rate',
        'zero-frames', 'too-long', 'truncated'])
def test_tts_rejects_invalid_oversized_or_truncated_input(payload):
    with pytest.raises(ValueError):
        prepare_ep_tts_wav(payload)


def test_latest_video_is_single_slot_copied_and_consumed_before_privacy():
    now = [5.0]
    inbox = EpVideoInbox(clock=lambda: now[0])
    frame = np.zeros((30, 40, 3), dtype=np.uint8)
    inbox.put(frame)
    frame[:] = 255
    latest = np.ones_like(frame)
    inbox.put(latest)
    latest[:] = 128
    assert np.all(inbox.take_for_privacy() == 1)
    assert inbox.take_for_privacy() is None


def test_invalid_frame_discards_older_frame_instead_of_replaying_it():
    inbox = EpVideoInbox()
    inbox.put(np.zeros((30, 40, 3), dtype=np.uint8))
    with pytest.raises(ValueError):
        inbox.put(None)
    assert inbox.take_for_privacy() is None


@pytest.mark.parametrize('elapsed', [.501, -1, float('nan'), float('inf')])
def test_video_stale_or_invalid_clock_is_dropped(elapsed):
    now = [1.0]
    inbox = EpVideoInbox(clock=lambda: now[0])
    inbox.put(np.zeros((30, 40, 3), dtype=np.uint8))
    now[0] += elapsed
    assert inbox.take_for_privacy() is None


@pytest.mark.parametrize('frame', [None, np.zeros((1, 1)),
    np.zeros((1, 1, 3), dtype=np.float32), np.zeros((721, 1280, 3), dtype=np.uint8)])
def test_video_rejects_foreign_or_oversized_frames(frame):
    with pytest.raises(ValueError):
        EpVideoInbox().put(frame)


def test_abi_metadata_never_enables_hardware_or_exposes_private_values():
    status = preparation_status({'status': 'dependency_review_required',
                                 'sdk_installed': True, 'private': 'secret'})
    assert status['target_model'] == 'EP'
    assert status['sdk_report_state'] == 'dependency_review_required'
    assert status['motion_enabled'] is status['video_enabled'] is status['audio_enabled'] is False
    assert status['hardware_acceptance'] is False
    assert 'secret' not in str(status)
    assert status['sdk_timeout_scope'] == 'host_timer_not_hardware_watchdog'


def test_preparation_status_never_imports_sdk_or_reads_robot(monkeypatch):
    import builtins
    original = builtins.__import__

    def deny_sdk(name, *args, **kwargs):
        assert not name.startswith('robomaster'), 'must not import SDK'
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', deny_sdk)
    assert preparation_status()['connection'] == 'not_connected'


def test_sta_plan_is_fixed_read_only_and_cannot_be_enabled_by_report():
    status = preparation_status({'connection_plan': {'mode': 'ap',
        'network_configuration_applied': True, 'discovery_enabled': True}})
    assert status['connection_plan'] == {
        'mode': 'sta_router', 'state': 'planned_not_configured',
        'pc_link': 'ethernet_to_same_router_preferred',
        'ep_link': 'wifi_to_same_router_pending_firmware_review',
        'firmware_state': 'awaiting_user_information',
        'network_configuration_applied': False, 'discovery_enabled': False,
        'router_credentials_stored': False, 'public_exposure_enabled': False,
        'remote_admin_access': 'not_configured_loopback_only',
    }


def test_preparation_routes_are_read_only_operator_scoped_and_no_cache():
    client = TestClient(hub.app)
    path = '/api/v1/robot/ep/preparation'
    assert client.get(path).status_code == 403
    headers = {'X-Operator-Key': 'unit-test-operator-only'}
    response = client.get(path, headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert response.json()['motion_enabled'] is False
    assert response.json()['connection_plan']['mode'] == 'sta_router'
    assert response.json()['connection_plan']['discovery_enabled'] is False
    assert client.post(path, headers=headers, json={'enabled': True}).status_code == 405
    # Live connection now exists, but still requires a body, local console and explicit confirmation.
    assert client.post('/api/v1/robot/ep/connect', headers=headers).status_code == 422


@pytest.mark.parametrize('raw,expected', [
    (b'{bad json', 'not_verified'),
    (b'x' * 64_001, 'not_verified'),
    (json.dumps({'status': 'blocked_native_wheel_abi', 'sdk_installed': True,
                 'private_url': 'private-do-not-echo'}).encode(), 'blocked_native_wheel_abi'),
], ids=['bad-json', 'oversized-report', 'untrusted-acceptance-flags'])
def test_saved_sdk_metadata_cannot_enable_capabilities_or_leak_details(monkeypatch, tmp_path, raw, expected):
    runtime = tmp_path / '.runtime'
    runtime.mkdir()
    (runtime / 'ep-sdk-preflight.json').write_bytes(raw)
    monkeypatch.setattr(hub, 'PROJECT_ROOT', tmp_path)
    response = TestClient(hub.app).get('/api/v1/robot/ep/preparation',
                                      headers={'X-Operator-Key': 'unit-test-operator-only'})
    assert response.json()['sdk_report_state'] == expected
    assert response.json()['sdk_import_verified'] is False
    assert response.json()['motion_enabled'] is False
    assert 'private-do-not-echo' not in response.text


def test_ep_page_starts_with_controls_disabled_and_has_no_capture_or_speech():
    response = TestClient(hub.app).get('/ep-preparation')
    assert response.status_code == 200
    assert response.headers['x-frame-options'] == 'DENY'
    assert "connect-src 'self'" in response.headers['content-security-policy']
    assert '<video' not in response.text and '<audio' not in response.text
    assert '開啟此頁不會移動 EP' in response.text
    assert '供 EP 掃描的組網 QR Code' in response.text
    assert 'id="armEp"' not in response.text
    for direction in ('forward', 'backward', 'left', 'right', 'turn_left', 'turn_right'):
        assert f'data-ep-direction="{direction}" disabled' in response.text
    assert 'ep-console.js' in response.text
    script = TestClient(hub.app).get('/assets/ep-preparation.js')
    assert script.status_code == 200
    assert script.headers['x-content-type-options'] == 'nosniff'
