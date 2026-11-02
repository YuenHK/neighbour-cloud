import numpy as np

from tools.calibrate_litter_classifier import find_weights, score_predictions


def test_calibration_weights_improve_bottle_can_boundary():
    probabilities = np.asarray(
        [
            [0.45, 0.50, 0.03, 0.02],
            [0.46, 0.49, 0.03, 0.02],
            [0.20, 0.70, 0.05, 0.05],
            [0.10, 0.80, 0.05, 0.05],
            [0.02, 0.03, 0.90, 0.05],
            [0.02, 0.03, 0.05, 0.90],
        ],
        dtype=np.float32,
    )
    truths = np.asarray([0, 0, 1, 1, 2, 3])

    weights = find_weights(probabilities, truths)
    baseline = score_predictions(truths, probabilities.argmax(axis=1))
    calibrated = score_predictions(truths, (probabilities * weights).argmax(axis=1))

    assert calibrated > baseline
    assert weights[0] > weights[1]
