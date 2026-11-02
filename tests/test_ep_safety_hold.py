from unittest.mock import Mock

import pytest

from edge_hub.ep_console import EpBroker
from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.robot_control import ControlError


def held_root(tmp_path):
    (tmp_path / '.runtime').mkdir()
    # Presence alone must fail closed, even with an incomplete JSON write.
    (tmp_path / '.runtime/ep-safety-hold.json').write_text('{')
    return tmp_path


@pytest.mark.parametrize('operation', [
    'connect', 'qr', 'prepare-control', 'lease', 'command', 'stop', 'reset',
    'gimbal-follow', 'gimbal-start', 'gimbal-target', 'speed', 'video-start', 'heartbeat',
])
def test_hold_never_starts_or_writes_worker(tmp_path, operation):
    broker = EpBroker(held_root(tmp_path))
    broker._start = Mock(side_effect=AssertionError('worker must not start'))
    broker.process = Mock()
    with pytest.raises(ControlError) as error:
        broker.request(operation)
    assert error.value.status == 423
    broker._start.assert_not_called()
    broker.process.stdin.write.assert_not_called()


def test_hold_passive_status_never_uses_stale_connected_cache(tmp_path):
    broker = EpBroker(held_root(tmp_path))
    broker.cached_status = {'connection': 'connected'}
    broker.process = Mock()
    for operation in ['status', 'health', 'disconnect', 'cancel-pairing']:
        status = broker.request(operation)
        assert status['safety_hold'] is True
        assert status['connection'] == 'not_connected'
        assert status['physical_stop_verified'] is False
    broker.process.stdin.write.assert_not_called()


def test_hold_survives_broker_recreation_and_prevents_monitor(tmp_path):
    root = held_root(tmp_path)
    for _ in range(2):
        fleet = EpFleetBroker(root)
        fleet.start_monitor()
        assert fleet.monitor_thread is None
        assert '暫停' in fleet.registry_notice
        with pytest.raises(ControlError):
            fleet._start()
        fleet.monitor_device({'broker': Mock(side_effect=AssertionError('no health probe'))})


def test_held_http_api_does_not_read_wifi_or_contact_workers(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from edge_hub.app import app, ep_broker
    from edge_hub.local_operator import LOCAL_OPERATOR_TOKEN

    monkeypatch.setattr(ep_broker, 'root', held_root(tmp_path))
    monkeypatch.setattr(ep_broker, '_start', Mock(side_effect=AssertionError('no SDK start')))
    monkeypatch.setattr('edge_hub.ep_console.current_wifi',
                        Mock(side_effect=AssertionError('no Wi-Fi access during hold')))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    headers = {'X-Operator-Key': LOCAL_OPERATOR_TOKEN}
    assert client.get('/ep-preparation').status_code == 200
    assert client.get('/api/v1/robot/ep/fleet', headers=headers).json()['safety_hold']
    assert client.post('/api/v1/robot/ep/qr', headers=headers,
                       json={'use_current_wifi': True}).status_code == 423
    for route in ['connect', 'prepare-control', 'lease', 'video-start']:
        assert client.post(f'/api/v1/robot/ep/devices/ep-1/{route}',
                           headers=headers, json={}).status_code == 423
