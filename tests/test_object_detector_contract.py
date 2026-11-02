from pathlib import Path

import numpy as np
import pytest

from edge_hub.vision import OnnxObjectDetector


class Session:
    def __init__(self, outputs):
        self.outputs, self.calls = outputs, 0

    def get_inputs(self):
        return [type('Input', (), {'name': 'images'})()]

    def run(self, *args):
        self.calls += 1
        return self.outputs


def detector(outputs):
    session = Session(outputs)
    return OnnxObjectDetector(Path('not-loaded.onnx'), session=session), session


@pytest.mark.parametrize('column,value', [(4, np.nan), (0, np.inf), (5, .5), (5, 4),
                                        (4, 1.1), (4, -.1), (0, -1), (2, 321), (2, 10)])
def test_invalid_rows_rejected_instead_of_clipped_truncated_or_ignored(column, value):
    row = np.array([[10, 10, 20, 20, .9, 0]], np.float32)
    row[0, column] = value
    instance, _ = detector([row])
    with pytest.raises(ValueError, match='detector'):
        instance.detect(np.zeros((320, 320, 3), np.uint8))


@pytest.mark.parametrize('outputs', [[], [np.ones((1, 6), np.int32)],
                                    [np.ones(6, np.float32)], [np.ones((2, 1, 6), np.float32)],
                                    [np.ones((1, 7), np.float32)],
                                    [np.ones((1, 6), np.float32), np.ones(1, np.float32)]])
def test_invalid_tensor_contract_is_rejected(outputs):
    instance, _ = detector(outputs)
    with pytest.raises(ValueError, match='detector'):
        instance.detect(np.zeros((20, 20, 3), np.uint8))


@pytest.mark.parametrize('threshold', [None, True, np.nan, np.inf, 0, -1, 1.01])
def test_bad_threshold_rejected_before_inference(threshold):
    instance, session = detector([np.empty((0, 6), np.float32)])
    with pytest.raises(ValueError, match='threshold'):
        instance.detect(np.zeros((20, 20, 3), np.uint8), threshold)
    assert session.calls == 0


@pytest.mark.parametrize('image', [np.zeros((2, 2), np.uint8), np.zeros((2, 2, 4), np.uint8),
                                  np.zeros((2, 2, 3), np.float32), np.zeros((0, 2, 3), np.uint8)])
def test_bad_image_rejected_before_inference(image):
    instance, session = detector([np.empty((0, 6), np.float32)])
    with pytest.raises(ValueError, match='image'):
        instance.detect(image)
    assert session.calls == 0


def test_valid_batched_rows_scale_and_do_not_modify_session_output():
    rows = np.array([[[32, 32, 160, 160, .9, 1]]], np.float32)
    original = rows.copy()
    instance, _ = detector([rows])
    result = instance.detect(np.zeros((640, 640, 3), np.uint8))
    assert result[0].label == 'aluminium_can' and result[0].box == (64, 64, 256, 256)
    assert np.array_equal(rows, original)
    empty, _ = detector([np.empty((0, 6), np.float32)])
    assert empty.detect(np.zeros((20, 20, 3), np.uint8)) == []


def test_bad_low_confidence_row_invalidates_whole_result():
    rows = np.array([[10, 10, 20, 20, .9, 0], [10, 10, 20, 20, .1, .5]], np.float32)
    instance, _ = detector([rows])
    with pytest.raises(ValueError, match='detector'):
        instance.detect(np.zeros((320, 320, 3), np.uint8))


def test_row_budget_is_enforced():
    rows = np.tile(np.array([[10, 10, 20, 20, .9, 0]], np.float32), (1001, 1))
    instance, _ = detector([rows])
    with pytest.raises(ValueError, match='tensor'):
        instance.detect(np.zeros((320, 320, 3), np.uint8))


def test_subpixel_box_is_not_returned_as_zero_size():
    instance, _ = detector([np.array([[10, 10, 10.1, 10.1, .9, 0]], np.float32)])
    with pytest.raises(ValueError, match='scaling'):
        instance.detect(np.zeros((20, 20, 3), np.uint8))
