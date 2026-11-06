import json
import re
from pathlib import Path


def test_reviewed_gallery_keeps_distinct_usable_imports_and_excludes_removed_series():
    catalogue = json.loads((Path(__file__).resolve().parents[1] / 'airi_overlay/cloud-model-gallery.json').read_text(encoding='utf-8'))
    rows = catalogue['models']
    assert len(rows) >= 26
    assert len(catalogue['excluded_sha256']) == 118
    assert not {row['sha256'] for row in rows}.intersection(catalogue['excluded_sha256'])
    assert not any('/100avatars-' in row['source'] for row in rows)
    assert len({row['id'] for row in rows}) == len(rows)
    assert len({row['sha256'] for row in rows}) == len(rows)
    assert sum(row.get('format', 'live2d-zip') == 'live2d-zip' for row in rows) >= 23
    for row in rows:
        assert re.fullmatch('[a-f0-9]{64}', row['sha256']) and 0 < row['bytes'] <= 32 * 1024 * 1024
        assert row['source'].startswith('https://') and row['license'].startswith('https://')
        assert row['image'].startswith('/assets/gallery/')
        if row.get('format') == 'vrm':
            assert row['license'] == 'https://creativecommons.org/publicdomain/zero/1.0/'
            if row['id'] in {'vroid-fumiriya', 'vroid-shino'}:
                assert re.fullmatch(r'https://raw\.githubusercontent\.com/madjin/vrm-samples/e16eb187100149a315ad92c3c9968f1d5baa6c7d/vroid/beta/(Sakurada_Fumiriya|Sendagaya_Shino)\.vrm', row['archive'])
                assert row['source'] in {
                    'https://vroid.pixiv.help/hc/en-us/articles/360014788554-Sakurada-Fumiriya',
                    'https://vroid.pixiv.help/hc/en-us/articles/360013482714-Sendagaya-Shino',
                }
            else:
                assert re.fullmatch(r'https://arweave\.net/[A-Za-z0-9_-]{43}', row['archive'])
                assert '/100avatars-r2.json' in row['source'] or '/100avatars-r3.json' in row['source']
        else:
            assert row['archive'].startswith('/assets/gallery/') and row['archive'].endswith('.zip')


def test_each_admitted_model_has_stable_first_added_metadata_for_cross_source_order():
    root = Path(__file__).resolve().parents[1]
    admissions = json.loads((root / 'airi_overlay/model-added.json').read_text(encoding='utf-8'))
    assert admissions['version'] == 1
    rows = [row for name in ('airi_overlay/cloud-model-gallery.json', 'deploy/cloud/vroid_reviewed.json',
                            'deploy/cloud/reviewed_model_imports.json')
            for row in json.loads((root / name).read_text(encoding='utf-8'))['models']]
    assert {row['sha256'] for row in rows} == set(admissions['added_ms'])
    assert all(type(value) is int and 0 < value < 8640000000000000 for value in admissions['added_ms'].values())


def test_new_original_live2d_sources_only_accept_their_own_repository_links():
    from deploy.cloud.gallery_registry import REGISTRY, valid_source_link
    assert REGISTRY['melba']['one_click_verified']
    assert REGISTRY['whale-girl']['one_click_verified']
    assert valid_source_link('https://github.com/NOM-Network/Melba-Toaster/blob/main/README.md', 'melba')
    assert valid_source_link('https://github.com/A8Chann/dsh-pet-live2d/tree/main/model-packs', 'whale-girl')
    assert not valid_source_link('https://github.com/other/repository', 'melba')
    assert not valid_source_link('https://github.com/NOM-Network/Melba-Toaster-fake', 'melba')
    assert not valid_source_link('https://github.com/NOM-Network/Melba-Toaster/%2e%2e/other', 'melba')
    assert not valid_source_link('https://user:secret@github.com/NOM-Network/Melba-Toaster', 'melba')
