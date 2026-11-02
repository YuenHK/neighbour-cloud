import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from edge_hub import vision_runtime
from edge_hub.events import EventStore


class FakeWorker:
    def __init__(self, **kwargs):
        self.alive = False
        self.joins = []

    def start(self):
        self.alive = True  # Never invoke the vision target or open a device.

    def is_alive(self):
        return self.alive

    def join(self, timeout):
        self.joins.append(timeout)
        self.alive = False


@pytest.fixture
def controlled(tmp_path, monkeypatch):
    person = tmp_path / 'fake-person.onnx'
    person.write_bytes(b'fixture only')
    monkeypatch.setenv('ZHIWEI_PERSON_MODEL', str(person))
    store = EventStore()
    runtime = vision_runtime.VisionRuntime(tmp_path, store, enabled=False)
    monkeypatch.setattr(runtime, '_model_accepted', lambda: True)
    monkeypatch.setattr(runtime, '_privacy_accepted', lambda: True)
    monkeypatch.setattr(vision_runtime.cv2, 'VideoCapture',
                        lambda *a, **k: pytest.fail('real device forbidden'))
    workers = []

    def factory(**kwargs):
        worker = FakeWorker(**kwargs)
        workers.append(worker)
        return worker

    # Replace only this module's reference, not the global threading.Thread.
    monkeypatch.setattr(vision_runtime, 'threading', SimpleNamespace(
        Thread=factory, current_thread=threading.current_thread))
    try:
        yield runtime, workers
    finally:
        store.close()


@pytest.mark.parametrize('second_operation', ['enable', 'disable'])
def test_concurrent_lifecycle_is_serialized(controlled, monkeypatch, second_operation):
    runtime, workers = controlled
    entered, release, attempted = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def gate():
        calls.append(True)
        entered.set()
        assert release.wait(5)
        return True

    def second():
        attempted.set()
        getattr(runtime, second_operation)()

    monkeypatch.setattr(runtime, '_model_accepted', gate)
    with ThreadPoolExecutor(max_workers=2) as callers:
        first = callers.submit(runtime.enable)
        try:
            assert entered.wait(5)
            acquired = runtime._lifecycle_lock.acquire(blocking=False)
            if acquired:
                runtime._lifecycle_lock.release()
            assert acquired is False
            other = callers.submit(second)
            assert attempted.wait(5)
        finally:
            release.set()
        first.result(timeout=5)
        other.result(timeout=5)
    assert len(workers) == len(calls) == 1
    assert runtime.enabled is (second_operation == 'enable')
    assert workers[0].alive is (second_operation == 'enable')
    assert runtime._stop.is_set() is (second_operation == 'disable')


def test_reentrant_controls_restart_only_after_worker_finishes(controlled):
    runtime, workers = controlled
    runtime.enable()
    runtime.enable()
    assert len(workers) == 1
    runtime.disable()
    assert workers[0].joins == [3]
    runtime.enable()
    assert len(workers) == 2 and not runtime._stop.is_set()
    runtime.disable()


def test_worker_can_request_stop_without_joining_itself(controlled):
    runtime, workers = controlled
    runtime._thread = threading.current_thread()
    runtime.stop()
    assert runtime._stop.is_set() and runtime._status == 'stopping'
    assert workers == []


@pytest.mark.parametrize('phase', ['construct', 'start'])
def test_launch_failure_is_redacted_stoppable_and_retryable(controlled, monkeypatch, phase):
    runtime, workers = controlled
    healthy_factory = vision_runtime.threading.Thread

    class Unstarted(FakeWorker):
        def start(self):
            raise RuntimeError('private path token secret')

        def join(self, timeout):
            pytest.fail('must not join an unstarted worker')

    def failing_factory(**kwargs):
        if phase == 'construct':
            raise OSError('private path token secret')
        return Unstarted(**kwargs)

    monkeypatch.setattr(vision_runtime.threading, 'Thread', failing_factory)
    runtime.enable()
    status = runtime.status()
    assert status['status'] == 'failed'
    assert status['error'] == 'vision worker start failed'
    assert status['worker_alive'] is False and status['stop_requested'] is True
    assert runtime._thread is None and workers == []
    runtime.disable()
    assert runtime.status()['status'] == 'failed'
    monkeypatch.setattr(vision_runtime.threading, 'Thread', healthy_factory)
    runtime.enable()
    assert len(workers) == 1 and workers[0].alive
    assert runtime._status == 'starting' and runtime._error is None
    assert not runtime._stop.is_set()
    runtime.disable()


def test_failed_launch_retains_unexpected_live_worker(controlled, monkeypatch):
    runtime, workers = controlled

    class UnexpectedLive(FakeWorker):
        def start(self):
            self.alive = True
            raise RuntimeError('private launch error')

    worker = UnexpectedLive()
    monkeypatch.setattr(vision_runtime.threading, 'Thread', lambda **kwargs: worker)
    runtime.enable()
    assert runtime._thread is worker and runtime._stop.is_set()
    assert runtime.status()['status'] == 'stopping'
    runtime.enable()
    assert runtime._thread is worker and runtime._stop.is_set()
    runtime.disable()
    assert worker.joins == [3] and runtime._status == 'failed'
    assert workers == []


def test_launch_does_not_overwrite_worker_published_state(controlled, monkeypatch):
    runtime, _ = controlled

    class Immediate(FakeWorker):
        def start(self):
            self.alive = True
            runtime._status = 'running'

    monkeypatch.setattr(vision_runtime.threading, 'Thread', Immediate)
    runtime.enable()
    assert runtime._status == 'running'
    runtime.disable()
