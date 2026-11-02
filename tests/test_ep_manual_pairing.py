from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr

from edge_hub.ep_acceptance import EpAcceptance
from edge_hub.ep_console import EpBroker
from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.ep_manual_pairing import EpManualPairing, ManualQrRequest, ep_manual_pairing_router
from edge_hub.robot_control import ControlError


class FakePairBroker:
    def __init__(self):
        self.calls = []
        self.ssid = ''
        self.image = None
        self.candidates = []

    def request(self, operation, payload=None):
        self.calls.append((operation, payload))
        if operation == 'qr':
            self.ssid, self.image = payload['ssid'], 'PHN2Zy8+'
        if operation in {'qr', 'qr-status'}:
            return {'svg_base64': self.image, 'ssid': self.ssid, 'revision': 'synthetic-revision'}
        return {'pairing': 'joined_network' if self.candidates else 'waiting_for_scan',
                'candidates': self.candidates}

    def close(self):
        self.calls.append(('disconnect', None))
        self.image = None


@pytest.fixture
def setup(tmp_path, monkeypatch):
    (tmp_path / '.runtime').mkdir()
    (tmp_path / '.runtime/ep-safety-hold.json').write_text('{')
    fleet = EpFleetBroker(tmp_path)
    for number in (1, 2):
        item = fleet.register(f'192.168.99.{number}')
        item['known_sn'] = 'SYNTHETIC-0930' if number == 2 else 'SYNTHETIC-1234'
    acceptance = EpAcceptance(fleet, broker=Mock())
    broker = FakePairBroker()
    pairing = EpManualPairing(fleet, acceptance, broker)
    wifi = Mock(return_value={'ssid': 'Synthetic-WLAN', 'password': 'synthetic-private-only'})
    monkeypatch.setattr('edge_hub.ep_manual_pairing.current_wifi', wifi)
    return fleet, acceptance, broker, pairing, wifi


def test_gets_do_not_read_wifi_start_pairing_or_connect(setup):
    _, acceptance, broker, pairing, wifi = setup
    pairing.state()
    pairing.qr()
    wifi.assert_not_called()
    acceptance.broker.request.assert_not_called()
    assert [op for op, _ in broker.calls] == ['status', 'qr-status']


def test_explicit_generation_keeps_key_inside_broker_and_blocks_acceptance(setup):
    fleet, acceptance, broker, pairing, wifi = setup
    result = pairing.generate(ManualQrRequest(device_id='ep-2'))
    wifi.assert_called_once_with(include_password=True)
    assert broker.calls == [('qr', {'ssid': 'Synthetic-WLAN', 'password': 'synthetic-private-only'})]
    assert 'synthetic-private-only' not in str(result)
    assert result['connection'] == 'not_connected' and not result['identity_verified']
    with pytest.raises(ControlError):
        acceptance.connect('ep-2', 3)
    acceptance.broker.request.assert_not_called()
    assert fleet.safety_hold()
    pairing.close()
    assert not pairing.active


def test_every_click_reads_current_wifi_and_optional_password_stays_hidden(setup):
    _, _, broker, pairing, wifi = setup
    wifi.side_effect = [
        {'ssid': 'Synthetic-Home', 'password': 'synthetic-home-only'},
        {'ssid': 'Synthetic-Exhibition', 'password': 'synthetic-event-only'},
        {'ssid': 'Synthetic-Current'},
    ]
    for _ in range(2):
        pairing.generate(ManualQrRequest(device_id='ep-2'))
    result = pairing.generate(ManualQrRequest(device_id='ep-2', password=SecretStr('synthetic-local-only')))
    assert [payload['ssid'] for op, payload in broker.calls if op == 'qr'] == [
        'Synthetic-Home', 'Synthetic-Exhibition', 'Synthetic-Current']
    assert wifi.call_args.kwargs == {'include_password': False}
    assert 'synthetic-local-only' not in str(result)


def test_wrong_target_or_existing_acceptance_prevents_any_wifi_read(setup):
    _, acceptance, broker, pairing, wifi = setup
    with pytest.raises(ControlError):
        pairing.generate(ManualQrRequest(device_id='ep-1'))
    acceptance.selected = 'ep-2'
    with pytest.raises(ControlError):
        pairing.generate(ManualQrRequest(device_id='ep-2'))
    wifi.assert_not_called()
    assert broker.calls == []


def test_pair_reply_does_not_connect_verify_sn_or_overwrite_known_ip(setup):
    fleet, acceptance, broker, pairing, _ = setup
    before = {key: item['ip'] for key, item in fleet.devices.items()}
    pairing.generate(ManualQrRequest(device_id='ep-2'))
    broker.candidates = [{'ip': '192.168.99.42', 'scan_id': 1}]
    for _ in range(4):
        state = pairing.state()
        assert not state['identity_verified'] and not state['movement_enabled']
    assert state['candidates'][0]['ip'] == '192.168.99.42'
    assert before == {key: item['ip'] for key, item in fleet.devices.items()}
    assert not fleet.registry_path.exists()
    acceptance.broker.request.assert_not_called()
    assert all(op in {'qr', 'status'} for op, _ in broker.calls)


@pytest.mark.parametrize('operation', [
    'connect', 'prepare-control', 'lease', 'command', 'stop', 'reset-stop', 'health',
    'gimbal-follow', 'gimbal-start', 'gimbal-target', 'gimbal-stop', 'speed',
    'video-start', 'video-frame', 'video-stop', 'video-heartbeat',
])
def test_pairing_broker_rejects_every_control_operation_before_worker(setup, operation):
    fleet, _, _, _, _ = setup
    broker = EpBroker(fleet.root, pairing_only=True)
    broker._start = Mock(side_effect=AssertionError('never launch'))
    with pytest.raises(ControlError) as error:
        broker.request(operation)
    assert error.value.status == 423
    broker._start.assert_not_called()


def test_pairing_worker_starts_only_from_qr_and_has_exclusive_role(setup, monkeypatch):
    fleet, _, _, _, _ = setup
    for relative in ['.runtime/ep-sdk/venv/Scripts/python.exe', '.runtime/ep-sdk/source/src/robomaster/robot.py']:
        path = fleet.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    worker = Mock(stdout=[])
    launch = Mock(return_value=worker)
    monkeypatch.setattr('edge_hub.ep_console.subprocess.Popen', launch)
    broker = EpBroker(fleet.root, pairing_only=True)
    broker.request('status')
    broker.request('qr-status')
    launch.assert_not_called()
    broker._start()
    assert '--pairing-only' in launch.call_args.args[0]
    assert '--acceptance-only' not in launch.call_args.args[0]
    with pytest.raises(ValueError):
        EpBroker(fleet.root, acceptance_only=True, pairing_only=True)


def test_http_requires_explicit_local_post_and_does_not_return_plain_key(setup):
    _, _, broker, pairing, wifi = setup
    app = FastAPI()
    def authorize(key):
        if key != 'synthetic-key':
            raise HTTPException(403)
    app.include_router(ep_manual_pairing_router(pairing, authorize,
                       Path(__file__).resolve().parents[1] / 'edge_hub/static'))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    headers = {'X-Operator-Key': 'synthetic-key'}
    assert client.get('/ep-manual-pairing').status_code == 200
    for route in ['status', 'qr']:
        assert client.get(f'/api/v1/robot/ep/manual-pairing/{route}', headers=headers).status_code == 200
    wifi.assert_not_called()
    route = '/api/v1/robot/ep/manual-pairing/qr'
    assert client.post(route, json={'device_id': 'ep-2'}).status_code == 403
    assert client.post(route, headers={**headers, 'Origin': 'http://other.invalid'},
                       json={'device_id': 'ep-2'}).status_code == 403
    wifi.assert_not_called()
    result = client.post(route, headers=headers, json={'device_id': 'ep-2'})
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    assert 'synthetic-private-only' not in result.text
    assert all(op in {'status', 'qr-status', 'qr'} for op, _ in broker.calls)


def test_production_validation_never_echoes_submitted_password(monkeypatch):
    from edge_hub.app import app, ep_manual_pairing
    monkeypatch.setattr(ep_manual_pairing, 'generate', Mock(side_effect=AssertionError('invalid request')))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    secret = 'synthetic-only-' * 10
    response = client.post('/api/v1/robot/ep/manual-pairing/qr',
        json={'device_id': 'ep-2', 'password': secret})
    assert response.status_code == 422 and secret not in response.text
