"""Fleet isolation tests use fake brokers, never SDK clients or robot sockets."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edge_hub.app import app, ep_broker
from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.local_operator import LOCAL_OPERATOR_TOKEN
from edge_hub.robot_control import ControlError


class FakeBroker:
    def __init__(self, root, device_id, sdk_port):
        self.device_id, self.sdk_port = device_id, sdk_port
        self.calls = []
        self.state = {'connection': 'not_connected', 'control': None}

    def request(self, operation, payload=None):
        self.calls.append((operation, payload))
        if operation == 'connect':
            self.state = {'connection': 'connected', 'ip': payload['ip'], 'control': None}
        if operation == 'lease':
            return {'lease_token': 'synthetic-' + self.device_id}
        return dict(self.state)

    def close(self):
        self.calls.append(('close', None))


def test_busy_primary_cannot_keep_an_old_connected_snapshot_alive(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    clock, busy, calls = [1000.0], [False], []
    monkeypatch.setattr('edge_hub.ep_fleet.time.monotonic', lambda: clock[0])
    def status(operation, payload=None):
        calls.append(operation)
        if busy[0]:
            raise ControlError('synthetic busy', 409)
        return {'connection':'connected','ip':'192.168.1.2','sn':'SYNTHETIC-FRESH',
                'battery_age_ms':100,'video_enabled':False,'control':None}
    monkeypatch.setattr(fleet, 'request', status)
    assert fleet.fleet_snapshot()['devices'][0]['connection'] == 'connected'
    busy[0] = True
    clock[0] += 1
    fresh = fleet.fleet_snapshot()['devices'][0]
    assert fresh['connection'] == 'connected' and fresh['status_cached']
    assert fresh['battery_age_ms'] == 1100
    clock[0] += 5
    stale = fleet.fleet_snapshot()['devices'][0]
    assert stale['connection'] == 'not_connected' and stale['status_stale']
    assert fleet.primary_snapshot_at == 1000.0
    assert set(calls) == {'status'}


def test_cached_secondary_battery_age_increases_and_unknown_timestamp_fails_closed():
    status = {'connection':'connected', 'battery_age_ms':4500, 'video_enabled':True, 'control':{'lease_active':False}}
    aged = EpFleetBroker.age_cached_snapshot(status, 100, now=100.6)
    assert aged['status_stale'] and not aged['video_enabled'] and aged['control'] is None
    assert status['connection'] == 'connected' and status['battery_age_ms'] == 4500
    assert EpFleetBroker.age_cached_snapshot(status, None)['connection'] == 'not_connected'


def test_manual_mode_does_not_start_monitor_or_reconnect(monkeypatch,tmp_path):
    runtime=tmp_path/'.runtime';runtime.mkdir()
    (runtime/'ep-manual-operation.json').write_text('{}')
    fleet=EpFleetBroker(tmp_path,FakeBroker)
    primary=FakeBroker(None,'primary',10100)
    primary.state={'connection':'not_connected','control':None,'candidates':[{'ip':'192.168.1.2','scan_id':1,'scan_received_at_ms':1000}]}
    monkeypatch.setattr(fleet,'request',primary.request)
    fleet.start_monitor()
    assert fleet.monitor_thread is None
    snapshot=fleet.fleet_snapshot()
    assert snapshot['manual_only'] and not snapshot['auto_monitoring']
    assert not snapshot['devices'][0]['auto_reconnect']
    fleet.monitor_device(fleet.devices['ep-1'])
    assert all(call[0]=='status' for call in primary.calls)


def fleet_fixture(monkeypatch):
    fleet = EpFleetBroker(Path('synthetic-unused'), FakeBroker)
    primary = FakeBroker(None, 'primary', 10100)
    primary.state = {'connection': 'not_connected', 'control': None, 'candidates': [
        {'ip': '192.168.1.2', 'scan_id': 1, 'scan_received_at_ms': 1000},
        {'ip': '192.168.1.3', 'scan_id': 2, 'scan_received_at_ms': 2000}]}
    monkeypatch.setattr(fleet, 'request', primary.request)
    return fleet, primary


def test_passive_fleet_discovers_two_without_connecting_or_starting_video(monkeypatch):
    fleet, primary = fleet_fixture(monkeypatch)
    result = fleet.fleet_snapshot()
    assert [item['id'] for item in result['devices']] == ['ep-1', 'ep-2']
    assert primary.calls == [('status', None)]
    peer = fleet.devices['ep-2']['broker']
    assert peer.calls == [('status', None)]
    assert peer.sdk_port == 12002


def test_selected_device_route_cannot_override_target_and_leases_never_cross(monkeypatch):
    fleet, primary = fleet_fixture(monkeypatch)
    fleet.fleet_snapshot()
    peer = fleet.devices['ep-2']['broker']
    fleet.device_request('ep-2', 'connect', {'ip': '192.168.1.99'})
    assert peer.calls[-1] == ('connect', {'ip': '192.168.1.3', 'confirmed': True})
    assert not any(operation == 'connect' for operation, _ in primary.calls)
    a = fleet.device_request('ep-1', 'lease')
    b = fleet.device_request('ep-2', 'lease')
    assert a['lease_token'] != b['lease_token']
    command = {'lease_token': b['lease_token'], 'direction': 'stop'}
    fleet.device_request('ep-2', 'command', command)
    assert peer.calls[-1] == ('command', command)
    assert not any(operation == 'command' for operation, _ in primary.calls)


def test_manual_disconnect_suppresses_only_that_devices_scan(monkeypatch):
    fleet, _ = fleet_fixture(monkeypatch)
    fleet.fleet_snapshot()
    fleet.device_request('ep-2', 'disconnect')
    devices = fleet.fleet_snapshot()['devices']
    assert devices[0]['auto_connect_suppressed_scan'] == 0
    assert devices[1]['auto_connect_suppressed_scan'] == 2


def test_unknown_device_does_not_start_worker(monkeypatch):
    fleet, primary = fleet_fixture(monkeypatch)
    with pytest.raises(ControlError) as caught:
        fleet.device_request('ep-9', 'video-start')
    assert caught.value.status == 404
    assert primary.calls == []


def test_broken_peer_does_not_hide_other_ep(monkeypatch):
    fleet, _primary = fleet_fixture(monkeypatch)
    fleet.fleet_snapshot()
    fleet.device_request('ep-1', 'connect')
    peer = fleet.devices['ep-2']['broker']
    def broken(*_):
        raise ControlError('synthetic timeout', 503)
    monkeypatch.setattr(peer, 'request', broken)
    devices = fleet.fleet_snapshot()['devices']
    assert devices[0]['connection'] == 'connected'
    assert devices[1]['connection'] == 'not_connected'
    assert devices[1]['error']


def test_fleet_capacity_and_duplicate_scan_do_not_allocate_more_workers(monkeypatch):
    fleet, _ = fleet_fixture(monkeypatch)
    assert fleet.register('192.168.1.2') is fleet.register('192.168.1.2')
    for index in range(3, 10):
        fleet.register(f'192.168.1.{index}')
    with pytest.raises(ControlError):
        fleet.register('192.168.1.10')


def test_device_routes_are_local_scoped_and_forward_only_selected_id(monkeypatch):
    calls = []
    monkeypatch.setattr(ep_broker, 'device_request', lambda *args: calls.append(args) or {'ok': True})
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    headers = {'X-Operator-Key': LOCAL_OPERATOR_TOKEN}
    route = '/api/v1/robot/ep/devices/ep-2/video-start'
    assert client.post(route).status_code == 403
    assert client.post(route, headers={**headers, 'Origin': 'https://example.com'}).status_code == 403
    assert calls == []
    assert client.post(route, headers=headers).status_code == 200
    assert calls == [('ep-2', 'video-start')]
    calls.clear()
    response = client.get('/api/v1/robot/ep/devices/ep-1/video-frame', headers=headers)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert calls == [('ep-1', 'video-frame')]


def test_known_ep_survives_restart_without_starting_worker_and_pins_identity(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    item = fleet.register('192.168.1.2')
    fleet.remember(item, {'connection': 'connected', 'sn': 'SYNTHETIC-SN-A'})
    restored = EpFleetBroker(tmp_path, FakeBroker)
    passive = FakeBroker(None, 'primary', 10100)
    monkeypatch.setattr(restored, 'request', passive.request)
    snapshot = restored.fleet_snapshot()['devices']
    assert len(snapshot) == 1 and snapshot[0]['remembered'] is True
    assert snapshot[0]['sn'] == 'SYNTHETIC-SN-A'
    assert snapshot[0]['connection'] == 'not_connected'
    assert passive.calls == [('status', None)]
    restored.device_request('ep-1', 'connect')
    assert passive.calls[-1] == ('connect', {'ip': '192.168.1.2', 'confirmed': True,
                                          'expected_sn': 'SYNTHETIC-SN-A'})


def test_unverified_scan_does_not_create_persistent_device_and_corrupt_registry_is_preserved(tmp_path):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    item = fleet.register('192.168.1.2')
    fleet.remember(item, {'connection': 'not_connected', 'sn': 'SYNTHETIC'})
    assert not fleet.registry_path.exists()
    fleet.registry_path.parent.mkdir(parents=True)
    original = b'synthetic invalid database retained'
    fleet.registry_path.write_bytes(original)
    restored = EpFleetBroker(tmp_path, FakeBroker)
    assert restored.registry_notice
    assert restored.registry_path.read_bytes() == original


def test_rescanning_same_identity_with_new_ip_updates_existing_menu_entry(tmp_path):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    first = fleet.register('192.168.1.2')
    fleet.remember(first, {'connection': 'connected', 'sn': 'SYNTHETIC-SN-A'})
    rescanned = fleet.register('192.168.1.33')
    canonical = fleet.remember(rescanned, {'connection': 'connected', 'sn': 'SYNTHETIC-SN-A'})
    assert canonical['id'] == 'ep-1'
    assert list(fleet.devices) == ['ep-1']
    restored = EpFleetBroker(tmp_path, FakeBroker)
    assert restored.devices['ep-1']['ip'] == '192.168.1.33'
    assert restored.devices['ep-1']['known_sn'] == 'SYNTHETIC-SN-A'


def test_background_monitor_reconnects_offline_without_controls_or_camera(monkeypatch):
    fleet, primary = fleet_fixture(monkeypatch)
    fleet.fleet_snapshot()
    primary.calls.clear()
    fleet.monitor_device(fleet.devices['ep-1'])
    assert [operation for operation, _ in primary.calls] == ['health', 'connect']
    assert fleet.devices['ep-1']['retry_at'] > 0
    assert not any(operation in {'prepare-control', 'lease', 'command', 'video-start'} for operation, _ in primary.calls)


def test_manual_disconnect_keeps_background_reconnect_paused(monkeypatch):
    fleet, primary = fleet_fixture(monkeypatch)
    fleet.fleet_snapshot()
    fleet.device_request('ep-1', 'disconnect')
    primary.calls.clear()
    fleet.monitor_device(fleet.devices['ep-1'])
    assert primary.calls == [('health', None)]


def test_monitor_failure_marks_offline_and_uses_bounded_retry_delay(monkeypatch):
    import time
    fleet, primary = fleet_fixture(monkeypatch)
    fleet.fleet_snapshot()
    def fail(*_):
        raise ControlError('synthetic offline', 503)
    monkeypatch.setattr(primary, 'request', fail)
    monkeypatch.setattr(fleet, 'request', fail)
    item = fleet.devices['ep-1']
    fleet.monitor_device(item)
    assert item['snapshot']['connection'] == 'not_connected'
    assert 0 < item['retry_at'] - time.monotonic() <= 30


@pytest.mark.parametrize('action,payload', [('speed', {'level': 5}), ('speed', {'level': True}),
    ('gimbal-follow', {'enabled': 'false'}), ('gimbal-target', {'generation': 1, 'seq': 0, 'issued_at_ms': 1, 'yaw': 61.0, 'pitch': 0.0})])
def test_invalid_configuration_never_reaches_sdk(action, payload, monkeypatch):
    monkeypatch.setattr(ep_broker, 'device_request', lambda *_: pytest.fail('invalid hardware request'))
    client = TestClient(app, base_url='http://127.0.0.1:8000', client=('127.0.0.1', 12000))
    assert client.post(f'/api/v1/robot/ep/devices/ep-1/{action}', json=payload,
        headers={'X-Operator-Key': LOCAL_OPERATOR_TOKEN}).status_code == 422
