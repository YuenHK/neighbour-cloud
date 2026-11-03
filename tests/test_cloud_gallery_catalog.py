import json
import re
from pathlib import Path


def test_reviewed_gallery_has_at_least_one_hundred_distinct_direct_imports():
    rows = json.loads((Path(__file__).resolve().parents[1] / 'airi_overlay/cloud-model-gallery.json').read_text(encoding='utf-8'))['models']
    assert len(rows) >= 100
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
