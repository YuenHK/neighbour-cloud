import json

from deploy.cloud.original_libraries import ROOT, snapshot
from deploy.cloud.reviewed_model_imports import STATIC_MODEL_CREDITS


def test_hundred_skins_distinguish_author_models_and_legal_derivatives_without_recounting_sources():
    gallery = json.loads((ROOT / 'airi_overlay/cloud-model-gallery.json').read_text(encoding='utf-8'))['models']
    live2d = [row for row in gallery if row.get('format') != 'vrm']
    derivatives = [row for row in live2d if row.get('derivative')]
    assert len(live2d) == 101 and len(derivatives) == 48
    assert len({row['sha256'] for row in live2d}) == 101
    original_ids = {row['id']: row for row in live2d if not row.get('derivative')}
    assert len(original_ids) == 53
    for row in derivatives:
        base = original_ids[row['base_id']]
        assert row['base_sha256'] == base['sha256'] and row['sha256'] != base['sha256']
        assert row['copyright'] == 'xShiroeNguyenx' and row['copyright'] in base['copyright']
        assert row['source'] == base['source'] and row['license'] == base['license']
        assert row['palette_label'] in row['name'] and '衍生' in row['individual_terms']
        assert 'CC BY-NC 4.0' in row['individual_terms'] and '原作者' in row['individual_terms']
        credit = STATIC_MODEL_CREDITS['cloud-live2d-' + row['sha256']]
        assert credit['notice'] == row['individual_terms'] and credit['author'] == row['copyright']
    originals = snapshot()
    assert originals['verified_independent_sources'] == 20 and originals['target_complete']
    counted = {item['id'] for source in originals['verified_libraries'] for item in source['models']}
    assert not counted.intersection(row['id'] for row in derivatives)
