import hashlib
import json

import pytest

from edge_hub.events import EventStore
from edge_hub.vision import LITTER_CLASSES
from edge_hub.vision_runtime import VisionRuntime


@pytest.mark.parametrize('change', ['missing', 'source', 'package'])
def test_litter_gate_rejects_stale_pipeline_even_when_model_and_scores_match(tmp_path, change):
    from edge_hub.vision import litter_pipeline_identity

    model = tmp_path / 'models/litter-classifier.onnx'
    model.parent.mkdir()
    model.write_bytes(b'fixture-model-not-loaded')
    report = {'model_sha256': hashlib.sha256(model.read_bytes()).hexdigest(),
              'evaluation_role': 'public-regression', 'formal_evaluation_eligible': True,
              'evaluation_scope': 'scene-events-with-background',
              'metrics': {'classes': {label: {'precision': .9, 'recall': .9} for label in LITTER_CLASSES}},
              'balanced_acceptance': {'passed': True, 'sample_counts': dict.fromkeys(LITTER_CLASSES, 20)},
              'pipeline_identity': litter_pipeline_identity()}
    path = model.with_suffix('.report.json')
    path.write_text(json.dumps(report), encoding='utf-8')
    runtime = VisionRuntime(tmp_path, EventStore(), enabled=False)
    assert runtime._model_accepted()
    if change == 'missing':
        report.pop('pipeline_identity')
    elif change == 'source':
        report['pipeline_identity']['vision_source_sha256'] = '0' * 64
    else:
        report['pipeline_identity']['numpy_version'] = 'changed'
    path.write_text(json.dumps(report), encoding='utf-8')
    assert not runtime._model_accepted()


def test_identity_uses_imported_source_not_new_disk_contents(monkeypatch):
    from pathlib import Path

    from edge_hub import vision

    before = vision.litter_pipeline_identity()
    original = Path.read_text
    def read(path, *a, **k):
        if path == Path(vision.__file__):
            pytest.fail('identity re-read potentially newer source file')
        return original(path, *a, **k)
    monkeypatch.setattr(Path, 'read_text', read)
    assert vision.litter_pipeline_identity() == before
