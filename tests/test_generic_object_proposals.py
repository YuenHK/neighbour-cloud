from types import SimpleNamespace

import numpy as np
import pytest

from edge_hub.object_proposals import GenericYoloxProposals


def session(raw):
    return SimpleNamespace(get_inputs=lambda: [SimpleNamespace(name='images', shape=[1, 3, 32, 32])],
                           run=lambda *args: [raw])


def output():
    raw = np.zeros((1, 21, 85), dtype=np.float32)
    raw[0, 0, 4] = .9
    raw[0, 0, 5 + 41] = .9
    return raw


def test_cup_proposal_is_namespaced_not_a_garbage_or_person_event():
    raw = output()
    original = raw.copy()
    detector = GenericYoloxProposals(None, input_size=32, session=session(raw))
    found = detector.detect(np.zeros((16, 32, 3), dtype=np.uint8))
    assert len(found) == 1 and found[0].kind == 'coco:cup'
    assert found[0].box == (0, 0, 4, 4)
    assert np.array_equal(raw, original)


def test_person_score_alone_never_produces_a_bottle_or_cup():
    raw = output()
    raw[0, 0, 5 + 41] = 0
    raw[0, 0, 5] = 1
    detector = GenericYoloxProposals(None, input_size=32, session=session(raw))
    assert detector.detect(np.zeros((16, 32, 3), dtype=np.uint8)) == []


@pytest.mark.parametrize('raw', [np.zeros((1, 21, 6)), np.full((1, 21, 85), np.nan)])
def test_wrong_contract_or_nonfinite_output_fails_closed(raw):
    detector = GenericYoloxProposals(None, input_size=32, session=session(raw))
    with pytest.raises(ValueError):
        detector.detect(np.zeros((16, 32, 3), dtype=np.uint8))


def test_duplicate_same_class_boxes_suppressed_but_scores_not_relabelled():
    raw = output()
    raw[0, 1] = raw[0, 0]
    raw[0, 1, 0] = -1  # Same decoded x centre despite next grid cell.
    detector = GenericYoloxProposals(None, input_size=32, session=session(raw))
    assert len(detector.detect(np.zeros((16, 32, 3), dtype=np.uint8))) == 1
