import json
from pathlib import Path

import numpy as np
import pytest

from edge_hub.vision import OnnxCropClassifier


class Session:
    def __init__(self, weights=None, scores=None):
        self.metadata = {} if weights is None else {'zhiwei_class_weights': weights}
        self.scores = np.array([[.1, .2, .3, .4]], np.float32) if scores is None else scores
        self.calls = 0

    def get_inputs(self):
        return [type('Input', (), {'name': 'images', 'shape': [1, 3, 16, 16]})()]

    def get_modelmeta(self):
        return type('Meta', (), {'custom_metadata_map': self.metadata})()

    def run(self, *args):
        self.calls += 1
        return [self.scores]


def classifier(session):
    return OnnxCropClassifier(Path('not-loaded.onnx'), session=session)


@pytest.mark.parametrize('encoded', ['[]', '[1,2,3]', '[1,2,3,0]', '[1,2,3,-1]',
                                    '[1,2,3,NaN]', '[1,2,3,Infinity]', '[true,1,1,1]',
                                    '["1",1,1,1]', 'not-json'])
def test_declared_bad_weights_cannot_silently_fall_back(encoded):
    with pytest.raises(ValueError, match='weights'):
        classifier(Session(encoded))


@pytest.mark.parametrize('scores', [np.array([[.1, .2, .3, 2]], np.float32),
                                   np.array([[1, 0, 0, 0]], np.int32),
                                   np.array([[.1, .2], [.3, .4]], np.float32)])
def test_invalid_probability_contract_is_rejected(scores):
    with pytest.raises(ValueError, match='probabilities'):
        classifier(Session(scores=scores)).probabilities(np.zeros((20, 20, 3), np.uint8))


def test_large_finite_weights_are_normalized_without_overflow():
    instance = classifier(Session(json.dumps([1e300, 2e300, 3e300, 4e300])))
    scores = instance.probabilities(np.zeros((20, 20, 3), np.uint8))
    assert np.isfinite(scores).all() and np.isclose(scores.sum(), 1)
    np.testing.assert_allclose(scores, np.array([1, 4, 9, 16]) / 30, rtol=1e-6)


@pytest.mark.parametrize('image', [np.zeros((2, 2, 3), np.float32), np.zeros((2, 2), np.uint8),
                                  np.zeros((0, 2, 3), np.uint8)])
def test_invalid_crop_is_rejected_before_session(image):
    session = Session()
    with pytest.raises(ValueError, match='crop'):
        classifier(session).probabilities(image)
    assert session.calls == 0


def test_regular_weights_match_existing_formula_and_unweighted_mode():
    instance = classifier(Session('[1,2,3,4]'))
    crop = np.zeros((20, 20, 3), np.uint8)
    np.testing.assert_allclose(instance.probabilities(crop), np.array([1, 4, 9, 16]) / 30, rtol=1e-6)
    np.testing.assert_allclose(instance.probabilities(crop, apply_weights=False), [.1, .2, .3, .4], rtol=1e-6)


def test_extreme_weight_ratio_keeps_only_nonzero_class_and_model_output_unchanged():
    session = Session(json.dumps([1e-300, 1e300, 1, 1]),
                      scores=np.array([[1, 0, 0, 0]], np.float64))
    original = session.scores.copy()
    scores = classifier(session).probabilities(np.zeros((20, 20, 3), np.uint8))
    np.testing.assert_array_equal(scores, [1, 0, 0, 0])
    np.testing.assert_array_equal(session.scores, original)


def test_zero_distribution_is_rejected():
    with pytest.raises(ValueError, match='empty'):
        classifier(Session(scores=np.zeros((1, 4), np.float32))).probabilities(np.zeros((20, 20, 3), np.uint8))


def test_mutated_runtime_weights_cannot_bypass_validation():
    instance = classifier(Session())
    instance.class_weights[0] = np.inf
    with pytest.raises(ValueError, match='weights'):
        instance.probabilities(np.zeros((20, 20, 3), np.uint8))
