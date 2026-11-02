import json
import time
from unittest.mock import Mock

import pytest

from edge_hub.ep_console import EpBroker
from edge_hub.robot_control import ControlError


def broker_with_old_ready(tmp_path, *, acceptance):
    broker = EpBroker(tmp_path, acceptance_only=acceptance)
    broker.process = Mock()
    broker.process.poll.return_value = None
    broker.cached_status = {'connection': 'connected', 'wheel_rest_confirmed': True,
                            'esc_diagnostics': {'sample_age_ms': 10}}
    broker.cached_status_at = time.monotonic()
    return broker


def test_acceptance_requests_new_worker_snapshot_even_inside_ordinary_cache_period(tmp_path):
    broker = broker_with_old_ready(tmp_path, acceptance=True)
    for age in (99, 150):
        broker.responses.put(json.dumps({'ok': True, 'result': {'wheel_rest_confirmed': False,
                                          'esc_diagnostics': {'sample_age_ms': age}}}))
        state = broker.request('status')
        assert state['wheel_rest_confirmed'] is False
        assert state['esc_diagnostics']['sample_age_ms'] == age
    assert broker.process.stdin.write.call_count == 2


def test_ordinary_console_retains_its_existing_display_cache(tmp_path):
    broker = broker_with_old_ready(tmp_path, acceptance=False)
    assert broker.request('status')['wheel_rest_confirmed'] is True
    broker.process.stdin.write.assert_not_called()


def test_busy_acceptance_does_not_fall_back_to_stale_ready(tmp_path):
    broker = broker_with_old_ready(tmp_path, acceptance=True)
    broker.lock = Mock()
    broker.lock.acquire.return_value = False
    with pytest.raises(ControlError):
        broker.request('status')
    broker.process.stdin.write.assert_not_called()
