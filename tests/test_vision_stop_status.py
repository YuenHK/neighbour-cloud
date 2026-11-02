import pytest

from edge_hub.events import EventStore
from edge_hub.vision_runtime import VisionRuntime


class ControlledThread:
    def __init__(self, alive=True, finish_on_join=False):
        self.alive, self.finish_on_join, self.joins = alive, finish_on_join, []

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.joins.append(timeout)
        if self.finish_on_join:
            self.alive = False


@pytest.fixture
def runtime(tmp_path):
    store = EventStore()
    runtime = VisionRuntime(tmp_path, store, enabled=False)
    try:
        yield runtime
    finally:
        store.close()


@pytest.mark.parametrize('disable', [False, True])
def test_live_worker_after_join_is_stopping_not_stopped_or_disabled(runtime, disable):
    runtime._thread = ControlledThread()
    runtime._status = 'running'
    runtime.enabled = True  # Local state fixture only; no start/enable or real worker.
    (runtime.disable if disable else runtime.stop)()
    status = runtime.status()
    assert runtime._thread.joins == [3]
    assert status['status'] == 'stopping'
    assert status['worker_alive'] is True and status['stop_requested'] is True
    assert status['enabled'] is (not disable)
    runtime._thread.alive = False
    assert runtime.status()['status'] == ('disabled' if disable else 'stopped')
    assert runtime.status()['worker_alive'] is False


@pytest.mark.parametrize('disable', [False, True])
def test_finished_worker_can_report_stopped_or_disabled(runtime, disable):
    runtime._thread = ControlledThread(finish_on_join=True)
    (runtime.disable if disable else runtime.stop)()
    status = runtime.status()
    assert status['status'] == ('disabled' if disable else 'stopped')
    assert status['worker_alive'] is False and status['stop_requested'] is True


def test_stop_does_not_hide_existing_release_failure(runtime):
    runtime._thread = ControlledThread(alive=False)
    runtime._status, runtime._error = 'failed', 'camera release failed'
    runtime.disable()
    assert runtime.status()['status'] == 'failed'
    assert runtime.status()['error'] == 'camera release failed'
    assert runtime.status()['enabled'] is False


def test_start_cannot_clear_stop_or_spawn_over_a_live_stopping_worker(runtime, monkeypatch):
    runtime._thread = ControlledThread()
    runtime._stop.set()
    runtime._status = 'stopping'
    monkeypatch.setattr(runtime, '_model_accepted', lambda: pytest.fail('must not restart'))
    runtime.start()
    assert runtime._stop.is_set() and runtime._status == 'stopping'


@pytest.mark.parametrize('phase', ['starting', 'running'])
def test_dead_worker_with_late_phase_cannot_appear_running_after_disable(runtime, phase):
    runtime._thread = ControlledThread(alive=False)
    runtime._stop.set()
    runtime._status = phase
    status = runtime.status()
    assert status['status'] == 'disabled'
    assert status['worker_alive'] is False
