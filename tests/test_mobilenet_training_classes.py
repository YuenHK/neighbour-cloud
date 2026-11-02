import pytest


def test_validation_selection_penalizes_false_positives_not_only_recall():
    torch = pytest.importorskip('torch')
    pytest.importorskip('torchvision')
    from tools.train_litter_mobilenet import _balanced_accuracy

    class AlwaysBottle(torch.nn.Module):
        def forward(self, inputs):
            return torch.tensor([[1., 0.]]).repeat(len(inputs), 1)

    loader = [(torch.zeros(4, 1), torch.tensor([0, 0, 1, 1]), ['a', 'b', 'c', 'd'])]
    assert _balanced_accuracy(AlwaysBottle(), loader) == .25


def test_background_rejections_keep_litter_false_accepts_and_misses():
    pytest.importorskip('torch')
    pytest.importorskip('torchvision')
    from edge_hub.metrics import LabeledBox
    from tools.train_litter_mobilenet import candidate_metrics

    truths = [LabeledBox('negative', 'background_unknown', (0, 0, 1, 1)),
              LabeledBox('positive', 'plastic_bottle', (0, 0, 1, 1))]
    predictions = [LabeledBox('negative', 'plastic_bottle', (0, 0, 1, 1)),
                   LabeledBox('positive', 'background_unknown', (0, 0, 1, 1))]
    result = candidate_metrics(truths, predictions)
    assert result['classes']['plastic_bottle']['fp'] == 1
    assert result['classes']['plastic_bottle']['fn'] == 1
    assert 'background_unknown' not in result['classes']


def test_training_dataset_supports_background_without_changing_four_class_default(tmp_path):
    pytest.importorskip('torch')
    pytest.importorskip('torchvision')
    import cv2
    import numpy as np

    from edge_hub.vision import LITTER_CLASSES
    from tools.train_litter_mobilenet import ManifestDataset

    cv2.imwrite(str(tmp_path / 'background.jpg'), np.full((80, 80, 3), 200, np.uint8))
    items = [{'path': 'background.jpg', 'split': 'train', 'label': 'background_unknown'}]
    dataset = ManifestDataset(tmp_path, items, 'train', training=False,
                              classes=(*LITTER_CLASSES, 'background_unknown'))
    image, label, identity = dataset[0]
    assert label == 4
    assert tuple(image.shape) == (3, 160, 160)
    assert identity == 'background.jpg'


def test_five_class_training_exports_evaluates_and_recovers_checkpoint(tmp_path, monkeypatch):
    torch = pytest.importorskip('torch')
    pytest.importorskip('torchvision')
    pytest.importorskip('onnx')
    import json

    import cv2
    import numpy as np

    from edge_hub.vision import LITTER_CLASSES, OnnxCropClassifier
    from tools import train_litter_mobilenet as training

    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.features = torch.nn.Sequential(torch.nn.Conv2d(3, 4, 1), torch.nn.AdaptiveAvgPool2d(1))
            self.classifier = torch.nn.Sequential(torch.nn.Linear(4, 4))

        def forward(self, inputs):
            return self.classifier(self.features(inputs).flatten(1))

    monkeypatch.setattr(training.models, 'mobilenet_v3_small', lambda **_: TinyModel())
    classes = [*LITTER_CLASSES, 'background_unknown']
    items = []
    for split in ('train', 'validation', 'test'):
        for index, label in enumerate(classes):
            path = f'{split}-{index}.jpg'
            cv2.imwrite(str(tmp_path / path), np.full((40, 40, 3), 20 + index * 40, np.uint8))
            items.append({'path': path, 'split': split, 'label': label})
    (tmp_path / 'manifest.json').write_text(json.dumps({'items': items, 'classes': classes}))
    model, report = tmp_path / 'tiny.onnx', tmp_path / 'report.json'
    result = training.train(tmp_path, model, report, epochs=1)
    assert model.exists() and model.with_suffix('.checkpoint.pt').exists()
    assert OnnxCropClassifier(model).classes == tuple(classes)
    assert result['background_metrics']['samples'] == 1
    assert result['formal_accuracy_accepted'] is False
    recovered = training.train(tmp_path, model, report, epochs=1, reuse_checkpoint=True)
    assert recovered['checkpoint_reused'] is True
    assert recovered['metrics'] == result['metrics']
