import asyncio

import pytest

from edge_hub.event_stream import EventFanout, stream_events
from edge_hub.events import Event


def event():
    return Event(id='offline-test', type='robot_fault', zone='simulation', at_ms=1, severity='notice')


class Socket:
    def __init__(self, blocked=False):
        self.incoming = asyncio.Queue()
        self.accepted = asyncio.Event()
        self.sending = asyncio.Event()
        self.closed = []
        self.sent = []
        self.blocked = blocked

    async def accept(self):
        self.accepted.set()

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, payload):
        self.sending.set()
        if self.blocked:
            await asyncio.Future()
        self.sent.append(payload)

    async def close(self, code):
        self.closed.append(code)


def test_overflow_is_explicit_and_does_not_block_other_subscribers():
    async def scenario():
        hub = EventFanout(queue_size=1, max_clients=2)
        slow, healthy = hub.subscribe(), hub.subscribe()
        assert hub.subscribe() is None
        hub.publish(event())
        healthy.queue.get_nowait()
        hub.publish(event())
        assert slow.overflowed and slow.queue.get_nowait() is None
        assert healthy.queue.get_nowait().id == 'offline-test'
        hub.publish(event())
        assert slow.queue.empty()  # Never accumulate more data after overflow.
    asyncio.run(scenario())


def test_idle_disconnect_releases_subscription_without_an_event():
    async def scenario():
        hub, socket = EventFanout(), Socket()
        task = asyncio.create_task(stream_events(socket, hub))
        await socket.accepted.wait()
        await socket.incoming.put({'type': 'websocket.disconnect'})
        await asyncio.wait_for(task, 1)
        assert not hub.subscribers
    asyncio.run(scenario())


def test_stalled_send_times_out_and_releases_subscription():
    async def scenario():
        hub, socket = EventFanout(), Socket(blocked=True)
        task = asyncio.create_task(stream_events(socket, hub, send_timeout=.02))
        await socket.accepted.wait()
        hub.publish(event())
        await asyncio.wait_for(task, 1)
        assert socket.closed == [1013] and not hub.subscribers
        assert hub.snapshot()['send_timeouts'] == 1
        assert hub.snapshot()['handshake_timeouts'] == 0
    asyncio.run(scenario())


def test_stream_sends_unchanged_event_and_overflow_closes_with_retry_code():
    async def scenario():
        hub, socket = EventFanout(queue_size=1), Socket()
        task = asyncio.create_task(stream_events(socket, hub))
        await socket.accepted.wait()
        hub.publish(event())
        await socket.sending.wait()
        assert socket.sent == [event().model_dump(mode='json', exclude_none=True)]
        hub.publish(event())
        hub.publish(event())
        await asyncio.wait_for(task, 1)
        assert socket.closed == [1013] and not hub.subscribers
    asyncio.run(scenario())


def test_connection_limit_does_not_register_extra_client():
    async def scenario():
        hub, socket = EventFanout(max_clients=1), Socket()
        hub.subscribe()
        await stream_events(socket, hub)
        assert socket.closed == [1013] and not socket.accepted.is_set()
        assert len(hub.subscribers) == 1
    asyncio.run(scenario())


def test_server_cancellation_cleans_up_idle_receive_and_queue_tasks():
    async def scenario():
        hub, socket = EventFanout(), Socket()
        task = asyncio.create_task(stream_events(socket, hub))
        await socket.accepted.wait()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.sleep(0)
        assert not hub.subscribers
        assert not [pending for pending in asyncio.all_tasks()
                    if pending is not asyncio.current_task() and not pending.done()]
    asyncio.run(scenario())


class StalledLifecycleSocket(Socket):
    def __init__(self, *, stall_accept=False, stall_close=False):
        super().__init__()
        self.stall_accept, self.stall_close = stall_accept, stall_close
        self.accept_started, self.close_started = asyncio.Event(), asyncio.Event()
        self.accept_cancelled = self.close_cancelled = False

    async def accept(self):
        self.accept_started.set()
        try:
            if self.stall_accept:
                await asyncio.Future()
            await super().accept()
        except asyncio.CancelledError:
            self.accept_cancelled = True
            raise

    async def close(self, code):
        self.close_started.set()
        try:
            if self.stall_close:
                await asyncio.Future()
            await super().close(code)
        except asyncio.CancelledError:
            self.close_cancelled = True
            raise


def assert_no_background_tasks():
    assert not [task for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()]


def test_stalled_handshake_and_close_release_capacity_and_tasks():
    async def scenario():
        hub = EventFanout(max_clients=1)
        socket = StalledLifecycleSocket(stall_accept=True, stall_close=True)
        await asyncio.wait_for(stream_events(socket, hub, handshake_timeout=.02,
                                             close_timeout=.02), 1)
        assert socket.accept_cancelled and socket.close_cancelled
        assert hub.snapshot()['handshake_timeouts'] == 1
        assert hub.snapshot()['close_timeouts'] == 1
        assert hub.snapshot()['send_timeouts'] == 0
        assert not socket.accepted.is_set() and not hub.subscribers
        assert_no_background_tasks()
        replacement = Socket()
        replacement.incoming.put_nowait({'type': 'websocket.disconnect'})
        await asyncio.wait_for(stream_events(replacement, hub), 1)
        assert replacement.accepted.is_set() and not hub.subscribers
    asyncio.run(scenario())


def test_rejected_client_stalled_close_is_bounded_without_removing_existing_client():
    async def scenario():
        hub = EventFanout(max_clients=1)
        existing = hub.subscribe()
        socket = StalledLifecycleSocket(stall_close=True)
        await asyncio.wait_for(stream_events(socket, hub, close_timeout=.02), 1)
        assert socket.close_cancelled and not socket.accept_started.is_set()
        assert hub.subscribers == {existing}
        assert hub.snapshot()['rejected_connections'] == 1
        assert hub.snapshot()['close_timeouts'] == 1
        assert_no_background_tasks()
    asyncio.run(scenario())


@pytest.mark.parametrize('stage', ['handshake', 'close'])
def test_lifecycle_cancellation_propagates_and_releases_owned_subscription(stage):
    async def scenario():
        hub = EventFanout(max_clients=1)
        socket = StalledLifecycleSocket(stall_accept=True, stall_close=True)
        task = asyncio.create_task(stream_events(socket, hub, handshake_timeout=.02))
        await asyncio.wait_for(
            socket.accept_started.wait() if stage == 'handshake' else socket.close_started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not hub.subscribers
        assert hub.snapshot()['handshake_timeouts'] == int(stage == 'close')
        assert hub.snapshot()['close_timeouts'] == 0
        assert_no_background_tasks()
    asyncio.run(scenario())


@pytest.mark.parametrize('value', [0, True, float('nan'), float('inf')])
@pytest.mark.parametrize('name', ['handshake_timeout', 'close_timeout'])
def test_invalid_lifecycle_budget_does_not_reserve_capacity(name, value):
    async def scenario():
        hub, socket = EventFanout(), Socket()
        with pytest.raises(ValueError, match='timeout'):
            await stream_events(socket, hub, **{name: value})
        assert not hub.subscribers and not socket.accepted.is_set()
    asyncio.run(scenario())
