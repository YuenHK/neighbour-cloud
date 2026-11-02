import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import HTTPException
from fastapi.responses import StreamingResponse

from edge_hub.resident_replay import TurnReplay
from local_audio_gateway.singleflight import SynthesisFlights


def test_speech_distinct_prefetch_overlaps_but_same_sentence_calls_once():
    flights = SynthesisFlights(2)
    gate = threading.Barrier(2)
    entered, release = threading.Event(), threading.Event()
    calls = []

    def generate():
        calls.append('same')
        entered.set()
        assert release.wait(2)
        return b'wave'

    with ThreadPoolExecutor(3) as pool:
        first = pool.submit(flights.run, 'same', generate)
        assert entered.wait(2)
        second = pool.submit(flights.run, 'same', generate)
        release.set()
        assert first.result() == second.result() == b'wave'
        assert calls == ['same']
        def overlap():
            gate.wait(timeout=2)
            return b'next'
        one = pool.submit(flights.run, 'one', overlap)
        two = pool.submit(flights.run, 'two', overlap)
        assert one.result() == two.result() == b'next'


def test_synthesis_failure_does_not_leave_queue_stuck():
    flights = SynthesisFlights(1)
    def fail():
        raise ValueError('synthetic')
    with pytest.raises(ValueError):
        flights.run('one', fail)
    assert not flights.pending
    assert flights.run('one', lambda: b'new') == b'new'


def test_replay_is_complete_only_and_isolated_by_session_turn_and_payload():
    async def run():
        replay = TurnReplay()
        headers = {'x-resident-session': 'a'*32, 'x-resident-turn': 'b'*32}
        key = replay.key(headers, {'messages': ['public']})
        assert replay.begin(key) is None
        with pytest.raises(HTTPException) as error:
            replay.begin(key)
        assert error.value.status_code == 409
        async def complete():
            yield b'data: {"choices":[]}\n\ndata: [DONE]\n\n'
        response = replay.wrap(key, StreamingResponse(complete()))
        expected = b''.join([part async for part in response.body_iterator])
        cached = replay.begin(key)
        assert b''.join([part async for part in cached.body_iterator]) == expected
        assert replay.key({**headers, 'x-resident-session': 'c'*32}, {'messages': ['public']}) != key
        assert replay.key({**headers, 'x-resident-turn': 'c'*32}, {'messages': ['public']}) != key
        assert replay.key(headers, {'messages': ['different']}) != key
        other = replay.key(headers, {'messages': ['partial']})
        replay.begin(other)
        async def partial():
            yield b'data: {"refusal":"failed"}\n\n'
        response = replay.wrap(other, StreamingResponse(partial()))
        _ = [part async for part in response.body_iterator]
        assert other not in replay.completed and other not in replay.pending
    asyncio.run(run())
