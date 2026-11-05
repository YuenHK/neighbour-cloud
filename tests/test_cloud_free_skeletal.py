import copy
import hashlib
import io
import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from PIL import Image
from test_cloud_avatar_assets import model_zip, store

from deploy.cloud.avatar_assets import install
from deploy.cloud.free_skeletal import FORMAT, validate_free_skeletal_archive
from deploy.cloud.presentation import Presentation, PresentationEdit
from deploy.cloud.presentation import install as install_presentation
from edge_hub.estate_services import EstateStore


def skeleton():
    return {'skeleton': {'spine': '3.8.99'}, 'bones': [{'name': 'root'}, {'name': 'mouth', 'parent': 'root'}],
            'slots': [{'name': 'body', 'bone': 'root', 'attachment': 'body'},
                      {'name': 'mouth', 'bone': 'mouth', 'attachment': 'mouth'}],
            'skins': {'default': {'body': {'body': {'path': 'body', 'width': 8, 'height': 8}},
                                  'mouth': {'mouth': {'path': 'body', 'width': 2, 'height': 1}}}},
            'animations': {'wave': {'bones': {'root': {'rotate': [{'time': 0, 'angle': 0}, {'time': .2, 'angle': 20}]}}}}}


ATLAS = 'original.png\nsize: 8,8\nformat: RGBA8888\nfilter: Linear,Linear\nrepeat: none\nbody\n  bounds: 0,0,8,8\n'


def free_zip(change=None, extra=None, atlas=ATLAS, manifest=None):
    picture = io.BytesIO()
    Image.new('RGBA', (8, 8), '#f2ba81').save(picture, format='PNG')
    doc = skeleton()
    if change:
        change(doc)
    files = {'rigby-manifest.json': json.dumps(manifest or {'format': FORMAT, 'skeleton': 'model.rigby.json',
             'atlas': 'model.atlas', 'license': {'name': 'CC0-1.0', 'author': 'Original synthetic fixture'}}).encode(),
             'model.rigby.json': json.dumps(doc).encode(), 'model.atlas': atlas.encode(),
             'original.png': picture.getvalue(), 'LICENSE.txt': b'Original synthetic fixture; CC0-1.0.'}
    files.update(extra or {})
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, value in files.items():
            archive.writestr(name, value)
    return output.getvalue()


@pytest.mark.parametrize('change', [
    lambda doc: doc['bones'][0].update(parent='root'),
    lambda doc: doc['bones'][1].update(parent='missing'),
    lambda doc: doc['bones'][1].update(x='NaN'),
    lambda doc: doc['bones'][1].update(y=float('inf')),
    lambda doc: doc['bones'][1].update(scaleX=True),
    lambda doc: doc['skins']['default']['body']['body'].update(path='https://outside.invalid/PRIVATE'),
    lambda doc: doc['skins']['default']['body']['body'].update(path='missing'),
    lambda doc: doc['skins']['default']['body']['body'].update(type='linkedmesh', parent='self'),
    lambda doc: doc['skins']['default']['body']['body'].update(type='mesh', uvs=[0, 0, 1, 0, 1, 1], vertices=[0], triangles=[0, 1, 2]),
    lambda doc: doc['skins']['default']['body']['body'].update(type='mesh', uvs=[0, 0, 1, 0, 1, 1], vertices=[0] * 6, triangles=[0, 1, 8]),
    lambda doc: doc['animations']['wave']['bones']['root']['rotate'].append({'time': -.1, 'angle': 0}),
    lambda doc: doc['animations']['wave'].update(events=[{'name': 'run'}]),
    lambda doc: doc.update(ik=[{'name': 'constraint'}]),
    lambda doc: doc.update(__proto__={'polluted': True}),
    lambda doc: doc['skeleton'].update(spine='4.1.0'),
    lambda doc: doc['skeleton'].update(images='data:image/png;base64,PRIVATE'),
])
def test_free_skeleton_rejects_external_cycles_nonfinite_unsupported_and_incomplete(change):
    with pytest.raises(ValueError):
        validate_free_skeletal_archive(free_zip(change))


@pytest.mark.parametrize('extra,atlas', [
    ({'../outside.txt': b'no'}, ATLAS),
    ({'run.js': b'no'}, ATLAS),
    ({'skeleton.skel': b'no'}, ATLAS),
    ({'Original.png': b'duplicate case'}, ATLAS),
    ({'unused.png': b'no'}, ATLAS),
    ({'original.png': b'<svg onload="alert(1)"/>'}, ATLAS),
    ({'model.rigby.json': b'{"bones":[],"bones":[]}'}, ATLAS),
    ({'model.rigby.json': b' ' * (3 * 1024 * 1024 + 1)}, ATLAS),
    ({}, ATLAS.replace('original.png', 'https://outside.invalid/run.png')),
    ({}, ATLAS.replace('size: 8,8', 'size: 99999,99999')),
    ({}, ATLAS.replace('bounds: 0,0,8,8', 'bounds: 0,0,9,8')),
])
def test_free_archive_rejects_extra_code_bad_size_paths_and_texture(extra, atlas):
    with pytest.raises(ValueError):
        validate_free_skeletal_archive(free_zip(extra=extra, atlas=atlas))


def test_only_explicit_free_manifest_and_separate_asset_licence_are_accepted():
    assert validate_free_skeletal_archive(free_zip()) == 'model.rigby.json'
    for manifest in [{'format': 'spine-zip'}, {'format': FORMAT, 'skeleton': 'model.rigby.json', 'atlas': 'model.atlas'}]:
        with pytest.raises(ValueError):
            validate_free_skeletal_archive(free_zip(manifest=manifest))


def test_free_models_use_same_immutable_store_and_schema_without_format_confusion(tmp_path):
    path = tmp_path / 'models.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        install(db)
        schema = db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
    assets = store(path)
    original = model_zip()
    old_id = 'cloud-live2d-' + hashlib.sha256(original).hexdigest()
    assets.put(old_id, 'original', original)
    content = free_zip()
    identity = 'cloud-rigby-' + hashlib.sha256(content).hexdigest()
    first = assets.put(identity, 'Original-free.rigby.zip', content)
    assert first['format'] == 'rigby-json-zip' and first['id'] == identity
    assert assets.put(identity, 'Do not overwrite', content) == first
    assert store(path).get(identity) == content
    assert assets.get(old_id) == original
    assert assets.get('cloud-live2d-' + first['sha256']) is None
    assert assets.get('cloud-vrm-' + first['sha256']) is None
    with pytest.raises(ValueError):
        assets.put('cloud-live2d-' + first['sha256'], 'wrong format', content)
    with closing(sqlite3.connect(path)) as db:
        assert schema == db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()


def test_free_model_requires_successful_upload_before_platform_publishing(tmp_path):
    estate = EstateStore(tmp_path / 'estate.sqlite3')
    try:
        install(estate.db)
        install_presentation(estate.db)
        settings = Presentation(estate)
        before = settings.current()
        body = copy.deepcopy({key: value for key, value in before.items() if key != 'revision'})
        content = free_zip()
        identity = 'cloud-rigby-' + hashlib.sha256(content).hexdigest()
        body['airi']['stage_model'] = identity
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            settings.save(PresentationEdit(expected_revision=1, **body))
        assert settings.current(refresh=True) == before
        store(estate.path).put(identity, 'Original.rigby.zip', content)
        assert settings.save(PresentationEdit(expected_revision=1, **body))['airi']['stage_model'] == identity
        body['airi']['stage_model'] = 'cloud-live2d-' + identity.removeprefix('cloud-rigby-')
        with pytest.raises(HTTPException):
            settings.save(PresentationEdit(expected_revision=2, **body))
    finally:
        estate.close()


def test_legacy_live2d_zip_is_not_silently_reclassified_as_free_skeletal():
    with pytest.raises(ValueError):
        validate_free_skeletal_archive(model_zip())
