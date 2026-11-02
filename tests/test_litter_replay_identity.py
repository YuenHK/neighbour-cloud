import json

import pytest

import tools.evaluate_litter_replay as module


def setup_replay(tmp_path, monkeypatch):
    model, manifest = tmp_path / 'fixture.onnx', tmp_path / 'manifest.json'
    model.write_bytes(b'fixture-model-not-loaded')
    manifest.write_text(json.dumps({'items': []}), encoding='utf-8')
    monkeypatch.setattr(module, 'OnnxCropClassifier', lambda _: object())
    class Processor:
        def __init__(self, *args):
            pass

        def detect(self, *args):
            return []
    monkeypatch.setattr(module, 'LitterFrameProcessor', Processor)
    return model, manifest


def test_replay_preserves_pipeline_and_does_not_gain_acceptance(tmp_path, monkeypatch):
    model, manifest = setup_replay(tmp_path, monkeypatch)
    report = module.replay(model, manifest)
    assert report['pipeline_identity'] == module.litter_pipeline_identity()
    assert len(report['model_sha256']) == len(report['manifest_sha256']) == 64
    assert not report['formal_accuracy_accepted']
    assert report['formal_evaluation_eligible'] is False
    assert report['evaluation_scope'] == 'synthetic-public-crop-scene-replay'
    assert report['images_saved'] == report['events_created'] == 0


@pytest.mark.parametrize('change', ['model', 'manifest', 'pipeline'])
def test_replay_rejects_changed_inputs(tmp_path, monkeypatch, change):
    model, manifest = setup_replay(tmp_path, monkeypatch)
    calls = []
    original = module.litter_pipeline_identity
    def identity():
        calls.append(1)
        if len(calls) == 2:
            if change == 'model':
                model.write_bytes(b'changed')
            elif change == 'manifest':
                manifest.write_text(json.dumps({'items': [], 'changed': True}), encoding='utf-8')
            else:
                return {'changed': True}
        return original()
    monkeypatch.setattr(module, 'litter_pipeline_identity', identity)
    with pytest.raises(ValueError, match='identity changed'):
        module.replay(model, manifest)


def test_cli_does_not_overwrite_existing_replay_report(tmp_path, monkeypatch):
    report = tmp_path / 'history.json'
    report.write_bytes(b'historical report')
    monkeypatch.setattr('sys.argv', ['replay', '--model', str(tmp_path / 'model.onnx'),
                                   '--manifest', str(tmp_path / 'manifest.json'), '--report', str(report)])
    monkeypatch.setattr(module, 'replay', lambda *a: pytest.fail('existing report triggered inference'))
    with pytest.raises(ValueError, match='new distinct'):
        module.main()
    assert report.read_bytes() == b'historical report'
