"""Bounded, best-effort event notifications; SQLite cursor pages remain authoritative."""
from __future__ import annotations

import asyncio
import math
import threading
from dataclasses import dataclass, field

from starlette.websockets import WebSocketDisconnect

from edge_hub.events import Event


@dataclass(eq=False)
class Subscription:
    queue: asyncio.Queue[Event | None]
    overflowed: bool = False


@dataclass
class EventFanout:
    queue_size: int = 100
    max_clients: int = 32
    subscribers: set[Subscription] = field(default_factory=set, init=False)
    _lock: object = field(default_factory=threading.Lock, init=False, repr=False, compare=False)
    _counts: dict[str, int] = field(default_factory=lambda: dict.fromkeys((
        'published_events', 'enqueued_notifications', 'overflowed_clients', 'rejected_connections',
        'handshake_timeouts', 'send_timeouts', 'close_timeouts'), 0), init=False, repr=False)

    def __post_init__(self):
        if self.queue_size < 1 or self.max_clients < 1:
            raise ValueError('fanout bounds must be positive')

    def subscribe(self):
        with self._lock:
            if len(self.subscribers) >= self.max_clients:
                self._counts['rejected_connections'] += 1
                return None
            subscription = Subscription(asyncio.Queue(maxsize=self.queue_size))
            self.subscribers.add(subscription)
            return subscription

    def unsubscribe(self, subscription):
        with self._lock:
            self.subscribers.discard(subscription)

    def record_timeout(self, stage):
        if stage not in ('handshake', 'send', 'close'):
            raise ValueError('unknown websocket timeout stage')
        with self._lock:
            self._counts[f'{stage}_timeouts'] += 1

    def snapshot(self):
        # HTTP diagnostics run on a worker thread; never expose subscriber objects.
        with self._lock:
            return {'scope': 'process-local best-effort event websocket; not delivery ACK',
                    'client_limit': self.max_clients, 'queue_capacity_per_client': self.queue_size,
                    'active_subscriptions': len(self.subscribers), **self._counts}

    def publish(self, event: Event):
        # Called only on the owning asyncio loop, never from a capture worker thread.
        with self._lock:
            self._counts['published_events'] += 1
            for subscription in tuple(self.subscribers):
                if subscription.overflowed:
                    continue
                if subscription.queue.full():
                    subscription.overflowed = True
                    self._counts['overflowed_clients'] += 1
                    while not subscription.queue.empty():
                        subscription.queue.get_nowait()
                    subscription.queue.put_nowait(None)  # Explicit reconnect, not silent data loss.
                else:
                    subscription.queue.put_nowait(event)
                    self._counts['enqueued_notifications'] += 1


async def stream_events(websocket, fanout: EventFanout, *, send_timeout=2.,
                        handshake_timeout=2., close_timeout=1.):
    for budget in (send_timeout, handshake_timeout, close_timeout):
        if (isinstance(budget, bool) or not isinstance(budget, (int, float))
                or not math.isfinite(budget) or not 0 < budget <= 30):
            raise ValueError('invalid event websocket timeout')

    async def retry_close():
        try:
            await asyncio.wait_for(websocket.close(code=1013), timeout=close_timeout)
        except TimeoutError:
            fanout.record_timeout('close')
        except (RuntimeError, OSError, WebSocketDisconnect):
            pass

    subscription = fanout.subscribe()
    if subscription is None:
        await retry_close()  # Rejected clients must not leave an unbounded close task.
        return
    disconnected = pending = None

    async def receive_disconnect():
        while True:
            if (await websocket.receive())['type'] == 'websocket.disconnect':
                return

    stage = 'handshake'
    try:
        await asyncio.wait_for(websocket.accept(), timeout=handshake_timeout)
        stage = 'send'
        disconnected = asyncio.create_task(receive_disconnect())
        while True:
            pending = asyncio.create_task(subscription.queue.get())
            done, _ = await asyncio.wait({disconnected, pending}, return_when=asyncio.FIRST_COMPLETED)
            if disconnected in done:
                return
            event = pending.result()
            if event is None or subscription.overflowed:
                await retry_close()
                return
            await asyncio.wait_for(websocket.send_json(event.model_dump(mode='json', exclude_none=True)),
                                   timeout=send_timeout)
    except TimeoutError:
        fanout.record_timeout(stage)
        await retry_close()
    except (WebSocketDisconnect, OSError, RuntimeError):
        pass  # A failed socket is not a failed SQLite write.
    finally:
        fanout.unsubscribe(subscription)
        tasks = [task for task in (pending, disconnected) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
