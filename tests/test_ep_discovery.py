import time
from types import SimpleNamespace

from edge_hub.ep_discovery import EpDiscovery
from edge_hub.ep_fleet import EpFleetBroker
from tests.test_ep_fleet import FakeBroker


def test_enabled_discovery_has_no_browser_expiry_and_close_still_stops():
    discovery = EpDiscovery()
    discovery.thread = SimpleNamespace(is_alive=lambda: True, join=lambda timeout: None)
    discovery.renew()
    assert discovery.until == float('inf')
    discovery.close()
    assert discovery.stop.is_set()


def test_passive_broadcast_parsing_rejects_non_robot_and_public_addresses():
    discovery = EpDiscovery()
    discovery.accept(b'3JKCK5L0030930\0', ('192.168.1.23', 40927))
    discovery.accept(b'3JKCK5L0030930\0', ('8.8.8.8', 40927))
    discovery.accept(b'not-a-robot', ('192.168.1.24', 40927))
    assert [item['ip'] for item in discovery.snapshot()] == ['192.168.1.23']


def test_page_lease_enables_known_robot_health_and_connection_without_motion(tmp_path, monkeypatch):
    runtime = tmp_path/'.runtime'
    runtime.mkdir()
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    primary = FakeBroker(None, 'primary', 10100)
    monkeypatch.setattr(fleet, 'request', primary.request)
    monkeypatch.setattr(fleet.discovery, 'renew', lambda: setattr(fleet.discovery, 'until', time.monotonic()+15))
    monkeypatch.setattr(fleet, 'start_monitor', lambda: None)
    fleet.renew_discovery()
    fleet.discovery.accept(b'3JKCK5L0030930\0', ('192.168.1.23', 40927))
    found = fleet.fleet_snapshot()
    assert found['discovery_active'] and len(found['devices']) == 1
    item = fleet.devices['ep-1']
    fleet.monitor_device(item)
    assert [call[0] for call in primary.calls] == ['status', 'health', 'connect']
    assert primary.calls[-1][1]['expected_sn'] == '3JKCK5L0030930'
    fleet.discovery.until = 0
    (runtime/'ep-manual-operation.json').write_text('{}')
    primary.calls.clear()
    fleet.monitor_device(item)
    assert not primary.calls


def test_manual_mode_cannot_be_overridden_by_page_discovery_or_old_lease(tmp_path, monkeypatch):
    runtime=tmp_path/'.runtime';runtime.mkdir()
    (runtime/'ep-manual-operation.json').write_text('{}')
    fleet=EpFleetBroker(tmp_path,FakeBroker)
    fleet.discovery.until=float('inf')
    monkeypatch.setattr(fleet.discovery,'renew',lambda:(_ for _ in ()).throw(AssertionError('no discovery')))
    monkeypatch.setattr(fleet,'start_monitor',lambda:(_ for _ in ()).throw(AssertionError('no monitor')))
    assert fleet.renew_discovery()=={'enabled':False,'mode':'manual_only','error':''}
    assert not fleet.auto_active()


def test_stale_battery_never_shows_powered_off_robot_as_online(tmp_path, monkeypatch):
    fleet = EpFleetBroker(tmp_path, FakeBroker)
    primary = FakeBroker(None, 'primary', 10100)
    monkeypatch.setattr(fleet, 'request', primary.request)
    fleet.register('192.168.1.23')
    primary.state = {'connection': 'connected', 'battery_age_ms': 9000, 'video_enabled': True}
    found = fleet.fleet_snapshot()['devices'][0]
    assert found['connection'] == 'not_connected' and found['video_enabled'] is False
