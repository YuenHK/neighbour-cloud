"""Synthetic judgments and mocked Ollama only; no hardware/provider access."""
import json
import time
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from edge_hub import ep_patrol
from edge_hub.events import EventStore
from edge_hub.observation_cache import ObservationCache


def frame_jpeg():
    ok, data = cv2.imencode('.jpg', np.full((360, 640, 3), 100, dtype=np.uint8))
    assert ok
    return data.tobytes()


def mock_local(monkeypatch, judgment):
    sent = []
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False
        def __enter__(self):
            return self
        def __exit__(self, *_):
            return False
        def post(self, url, *, json):
            assert url == 'http://127.0.0.1:11434/api/chat'
            sent.append(json)
            return SimpleNamespace(raise_for_status=lambda: None,
                json=lambda: {'message': {'content': __import__('json').dumps(judgment)}})
    monkeypatch.setattr(ep_patrol.httpx, 'Client', Client)
    monkeypatch.setattr(ep_patrol, '_observations', ObservationCache())
    monkeypatch.setattr('edge_hub.object_hints.object_hints', lambda _: ['cup'])
    return sent


def test_bare_labels_are_not_grounded_water_evidence(monkeypatch):
    calls = mock_local(monkeypatch, {'findings': ['standing_water']})
    with pytest.raises(ValueError, match='observation'):
        ep_patrol.local_observe(frame_jpeg(), False)
    assert len(calls) == 1  # Invalid output is not blindly replayed.


@pytest.mark.parametrize('cue', ['reflection_only', 'uncertain', 'object_in_normal_use'])
def test_reflections_or_uncertainty_cannot_become_water_or_litter(monkeypatch, cue):
    calls = mock_local(monkeypatch, {'findings': [
        {'kind': 'standing_water', 'cue': cue}, {'kind': 'litter', 'cue': cue}]})
    assert ep_patrol.local_observe(frame_jpeg(), False) == set()
    assert len(calls) == 1
    assert calls[0]['format']['properties']['findings']['items']['type'] == 'object'


def test_matching_visible_cues_pass_but_incompatible_cues_and_people_are_gated(monkeypatch):
    mock_local(monkeypatch, {'findings': [
        {'kind': 'standing_water', 'cue': 'pool_boundary'},
        {'kind': 'litter', 'cue': 'visible_flame'},
        {'kind': 'restricted_presence', 'cue': 'person_in_marked_area'},
        {'kind': 'electrical_hazard', 'cue': 'exposed_damaged_wire'}]})
    assert ep_patrol.local_observe(frame_jpeg(), False) == {'standing_water', 'electrical_hazard'}
    assert ep_patrol.local_observe(frame_jpeg(), True) == {
        'standing_water', 'electrical_hazard', 'restricted_presence'}


def test_grounded_urgent_candidates_do_not_require_model_confidence(monkeypatch):
    sent = mock_local(monkeypatch, {'findings': [
        {'kind': 'smoke_flame', 'cue': 'visible_smoke'},
        {'kind': 'electrical_hazard', 'cue': 'visible_sparks'}]})
    assert ep_patrol.local_observe(frame_jpeg(), False) == {'smoke_flame', 'electrical_hazard'}
    assert 'confidence' not in json.dumps(sent[0]['format'])
    assert sent[0]['model'] == 'qwen3.5:2b'


@pytest.mark.parametrize('bad', [
    {'findings': [{'kind': 'standing_water', 'cue': 'AI_says_so'}]},
    {'findings': [{'kind': 'standing_water', 'cue': 'pool_boundary', 'confidence': 1}]},
    {'findings': [{'kind': 'smoke_flame', 'cue': 'visible_smoke'}], 'execute': 'move'},
])
def test_unknown_or_extra_model_fields_fail_closed(monkeypatch, bad):
    mock_local(monkeypatch, bad)
    with pytest.raises(ValueError, match='observation'):
        ep_patrol.local_observe(frame_jpeg(), False)


def manager(tmp_path, observe):
    now = int(time.time()*1000)
    frame = {'state': 'frame', 'jpeg': frame_jpeg(), 'key': 'epoch-1',
             'sn': 'SYNTHETIC', 'captured_at_ms': now-55000}
    events = EventStore(tmp_path/'events.sqlite3')
    patrol = ep_patrol.EpPatrol(lambda _: dict(frame), events, tmp_path/'data', observe,
        background=False, context_source=lambda *_: [])
    reports = []
    patrol.report = lambda device, settings, anchor, kind, *args, **kwargs: reports.append(kind)
    patrol.configure('test', ep_patrol.PatrolSettings(enabled=True))
    return frame, patrol, events, reports, now


def test_expired_or_reverse_capture_observation_cannot_confirm_new_candidate(tmp_path, monkeypatch):
    frame, patrol, events, reports, now = manager(tmp_path, lambda *_: {'litter'})
    clock = [now/1000]
    monkeypatch.setattr(ep_patrol.time, 'time', lambda: clock[0])
    try:
        frame['captured_at_ms'] = now-1000
        patrol.step('test')
        # Both frames individually fresh, but two observations are over 60s apart.
        clock[0] += 90
        frame.update(key='epoch-2', captured_at_ms=now+90000)
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert reports == []
        frame.update(key='epoch-3', captured_at_ms=now+89000)
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert reports == []  # Out-of-order captures do not count as confirmation.
    finally:
        patrol.close()
        events.close()


def test_short_window_confirms_nonurgent_and_urgent_remains_single_frame(tmp_path):
    frame, patrol, events, reports, now = manager(tmp_path, lambda *_: {'litter'})
    try:
        frame['captured_at_ms'] = now-1000
        patrol.step('test')
        frame.update(key='epoch-2', captured_at_ms=now)
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert reports == ['litter']
        patrol.observe = lambda *_: {'smoke_flame', 'electrical_hazard'}
        frame.update(key='epoch-3', captured_at_ms=now+1)
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert set(reports) == {'litter', 'smoke_flame', 'electrical_hazard'}
    finally:
        patrol.close()
        events.close()


def test_capture_identity_change_never_confirms_other_robot(tmp_path):
    frame, patrol, events, reports, now = manager(tmp_path, lambda *_: {'litter'})
    try:
        frame['captured_at_ms'] = now-1000
        patrol.step('test')
        frame.update(key='epoch-2', captured_at_ms=now, sn='OTHER-SYNTHETIC')
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert reports == []
    finally:
        patrol.close()
        events.close()


def test_equal_timestamp_new_key_is_not_a_second_capture(tmp_path):
    frame, patrol, events, reports, now = manager(tmp_path, lambda *_: {'litter'})
    try:
        frame['captured_at_ms'] = now-1000
        patrol.step('test')
        frame['key'] = 'epoch-2'
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert reports == []
        frame.update(key='epoch-3', captured_at_ms=now-999)
        patrol.states['test']['next_at'] = 0
        patrol.step('test')
        assert reports == ['litter']
    finally:
        patrol.close()
        events.close()
