import numpy as np

from edge_hub.vision import crop_features
from tools.train_litter_classifier import augmented_versions


def test_features_have_stable_finite_shape() -> None:
    features = crop_features(np.zeros((80, 40, 3), dtype=np.uint8))

    assert features.ndim == 1
    assert len(features) > 1000
    assert np.isfinite(features).all()


def test_training_augmentation_does_not_mutate_input() -> None:
    image = np.full((20, 20, 3), 100, dtype=np.uint8)
    original = image.copy()

    versions = augmented_versions(image)

    assert len(versions) == 4
    assert np.array_equal(image, original)
