import time

import pytest

from edge_hub.ep_fleet import EpFleetBroker
from edge_hub.robot_control import ControlError
from tests.test_ep_fleet import FakeBroker


def test_all_verified_serials_survive_restart_and_offline(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    for index, sn in enumerate(('TEST-SN-0930', 'TEST-SN-0234'), 1):
        item = fleet.register(f'192.168.1.{index}')
        fleet.remember(item, {'connection': 'connected', 'sn': sn})
    restored = EpFleetBroker(tmp_path, FakeBroker)
    monkeypatch.setattr(restored, 'request', lambda *_: {'connection': 'not_connected'})
    snapshot = restored.fleet_snapshot()
    assert {item['sn'] for item in snapshot['devices']} == {'TEST-SN-0930', 'TEST-SN-0234'}
    assert all(item['remembered'] and item['connection'] == 'not_connected' for item in snapshot['devices'])


def test_forget_offline_record_is_persistent_and_not_readded_by_broadcast(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    item = fleet.register('192.168.1.2')
    fleet.remember(item, {'connection': 'connected', 'sn': '3JKCK5L0030234'})
    monkeypatch.setattr(fleet, 'request', lambda *_: {'connection': 'not_connected'})
    assert fleet.forget(item['id'])['removed']
    fleet.remember(item, {'connection': 'connected', 'sn': '3JKCK5L0030234'})  # Late completion.
    restored = EpFleetBroker(tmp_path, FakeBroker)
    monkeypatch.setattr(restored, 'request', lambda *_: {'connection': 'not_connected'})
    restored.discovery.until = float('inf')
    restored.discovery.accept(b'3JKCK5L0030234\0', ('192.168.1.2', 40927))
    assert restored.fleet_snapshot()['devices'] == []


def test_forget_never_disconnects_an_online_robot(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    item = fleet.register('192.168.1.2')
    calls = []
    def request(operation, payload=None):
        calls.append(operation)
        return {'connection': 'connected'}
    monkeypatch.setattr(fleet, 'request', request)
    with pytest.raises(ControlError):
        fleet.forget(item['id'])
    assert calls == ['status'] and item['id'] in fleet.devices


def test_fresh_scan_can_restore_removed_robot(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    item = fleet.register('192.168.1.2')
    fleet.remember(item, {'connection': 'connected', 'sn': '3JKCK5L0030234'})
    monkeypatch.setattr(fleet, 'request', lambda *_: {'connection': 'not_connected'})
    fleet.forget(item['id'])
    fresh = fleet.register('192.168.1.22')
    fresh['scan_received_at_ms'] = int(time.time()*1000)+1
    fleet.remember(fresh, {'connection': 'connected', 'sn': '3JKCK5L0030234'})
    restored = EpFleetBroker(tmp_path, FakeBroker)
    assert [item['known_sn'] for item in restored.devices.values()] == ['3JKCK5L0030234']
