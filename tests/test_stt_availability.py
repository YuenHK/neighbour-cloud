import asyncio
import json

import pytest
from fastapi import HTTPException

from local_audio_gateway.stt_availability import SttAvailability


def test_outage_blocks_new_audio_without_retransmitting_then_recovers():
    async def check():
        now = [100.0]
        guard = SttAvailability(clock=lambda: now[0])
        calls = []

        async def fail():
            calls.append('first')
            raise HTTPException(503, 'private URL and secret must not be recorded')

        with pytest.raises(HTTPException, match='503'):
            await guard.run(fail)
        with pytest.raises(HTTPException) as blocked:
            await guard.run(fail)
        assert blocked.value.headers == {'Retry-After': '15'}
        assert calls == ['first']
        assert 'secret' not in json.dumps(guard.snapshot())
        now[0] += 15

        async def success():
            return 'synthetic transcript'

        assert await guard.run(success) == 'synthetic transcript'
        assert guard.snapshot()['last_result'] == 'succeeded'
        assert guard.snapshot()['automatic_retries'] is False
    asyncio.run(check())


def test_deadline_cancels_one_request_without_retry():
    async def check():
        guard = SttAvailability(deadline=0.01)
        cancelled = []

        async def slow():
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.append(True)

        with pytest.raises(HTTPException) as error:
            await guard.run(slow)
        assert error.value.status_code == 504
        assert cancelled == [True]
        assert guard.snapshot()['failures'] == 1
        assert guard.snapshot()['last_result'] == 'deadline_exceeded'
    asyncio.run(check())


def test_only_one_recovery_probe_and_cancel_does_not_lock_it_forever():
    async def check():
        now = [100.0]
        guard = SttAvailability(clock=lambda: now[0])

        async def fail():
            raise HTTPException(503)

        with pytest.raises(HTTPException):
            await guard.run(fail)
        now[0] += 15
        entered = asyncio.Event()

        async def pending():
            entered.set()
            await asyncio.Event().wait()

        probe = asyncio.create_task(guard.run(pending))
        await entered.wait()
        with pytest.raises(HTTPException):
            await guard.run(fail)
        probe.cancel()
        with pytest.raises(asyncio.CancelledError):
            await probe
        assert guard.snapshot()['probe_in_flight'] is False
        assert guard.snapshot()['failures'] == 1
    asyncio.run(check())


@pytest.mark.parametrize('status', [400, 401, 403, 413])
def test_invalid_request_does_not_trip_availability(status):
    async def check():
        guard = SttAvailability()

        async def invalid():
            raise HTTPException(status)

        with pytest.raises(HTTPException):
            await guard.run(invalid)
        assert guard.snapshot()['failures'] == 0
    asyncio.run(check())


@pytest.mark.parametrize('duration', [0, -1, float('nan'), float('inf'), 61])
def test_timing_validation(duration):
    with pytest.raises(ValueError):
        SttAvailability(deadline=duration)
