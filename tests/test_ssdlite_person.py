import numpy as np
import pytest

from tools.evaluate_ssdlite_person import cache, decode_detections, verified_weight


def prediction():
    return {'boxes': np.array([[-5, 10, 50, 110], [0, 0, 50, 50]], dtype=np.float32),
            'scores': np.array([.9, .9], dtype=np.float32),
            'labels': np.array([1, 2], dtype=np.int64)}


def test_only_person_boxes_are_scaled_clipped_and_input_unchanged():
    output = prediction()
    saved = {key: value.copy() for key, value in output.items()}
    assert decode_detections(output, 100, 100, .15) == [(0, 10, 50, 90)]
    for key, value in output.items():
        np.testing.assert_array_equal(value, saved[key])
    output['scores'][0] = .1
    assert decode_detections(output, 100, 100, .15) == []


@pytest.mark.parametrize('failure', ['nan', 'label', 'shape', 'geometry'])
def test_invalid_detection_tensor_rejected(failure):
    output = prediction()
    if failure == 'nan':
        output['scores'][0] = np.nan
    elif failure == 'label':
        output['labels'][0] = 91
    elif failure == 'shape':
        output['boxes'] = np.zeros((2, 5))
    else:
        output['boxes'][0, 2] = -10
    with pytest.raises(ValueError):
        decode_detections(output, 100, 100, .15)


def test_boolean_threshold_and_float_labels_rejected():
    with pytest.raises(ValueError):
        decode_detections(prediction(), 100, 100, True)
    output = prediction()
    output['labels'] = output['labels'].astype(np.float32)
    with pytest.raises(ValueError):
        decode_detections(output, 100, 100, .15)


def test_cache_bad_upstream_hash_writes_nothing_and_refuses_existing(tmp_path):
    destination = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='prefix'):
        cache(destination, lambda *args, **kwargs: b'unreviewed weights')
    assert not destination.exists()
    destination.mkdir()
    with pytest.raises(FileExistsError):
        cache(destination, lambda *args, **kwargs: b'unreviewed weights')


def test_weights_require_full_expected_digest_and_known_prefix(tmp_path):
    path = tmp_path / 'weights.pth'
    path.write_bytes(b'not an official model')
    with pytest.raises(ValueError, match='full lowercase'):
        verified_weight(path, 'a79551df')
    with pytest.raises(ValueError, match='mismatch'):
        verified_weight(path, '0' * 64)
