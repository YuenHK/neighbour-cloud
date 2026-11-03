import copy
import hashlib
import io
import json
import sqlite3
import struct
from contextlib import closing

import pytest
import test_cloud_avatar_api as shared_api
from PIL import Image
from test_cloud_avatar_assets import model_zip, store

from deploy.cloud.avatar_assets import install
from deploy.cloud.avatar_vrm import REQUIRED_BONES, validate_vrm

models_api = shared_api.models_api
prepared = shared_api.prepared
seeded = shared_api.seeded


def model_vrm(change=None):
    image = io.BytesIO()
    Image.new('RGB', (8, 8), 'green').save(image, format='PNG')
    binary = image.getvalue()
    bones = sorted(REQUIRED_BONES)
    doc = {'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(binary)}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(binary)}],
        'images': [{'bufferView': 0, 'mimeType': 'image/png'}], 'meshes': [{'primitives': []}],
        'nodes': [{'name': name} for name in bones], 'extensions': {'VRM': {
            'meta': {'author': 'Public test fixture', 'licenseName': 'CC0'},
            'humanoid': {'humanBones': [{'bone': name, 'node': index} for index, name in enumerate(bones)]}}}}
    if change:
        change(doc)
    encoded = json.dumps(doc).encode()
    encoded += b' ' * (-len(encoded) % 4)
    binary += b'\0' * (-len(binary) % 4)
    return struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(binary)) + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded + struct.pack('<II', len(binary), 0x004E4942) + binary


@pytest.mark.parametrize('change', [
    lambda d: d['buffers'][0].update(uri='https://outside.invalid/PRIVATE'),
    lambda d: d['images'][0].update(uri='file:///PRIVATE'),
    lambda d: d['bufferViews'][0].update(byteOffset=-1),
    lambda d: d['nodes'][0].update(children=[0]),
    lambda d: d['nodes'][0].update(translation=[float('nan'), 0, 0]),
    lambda d: d['extensions']['VRM']['humanoid']['humanBones'].clear(),
])
def test_vrm_rejects_external_incomplete_or_cyclic_models(change):
    with pytest.raises(ValueError):
        validate_vrm(model_vrm(change))


def test_vrm_and_live2d_share_existing_store_without_schema_or_identifier_confusion(tmp_path):
    path = tmp_path / 'models.sqlite3'
    with closing(sqlite3.connect(path)) as db:
        install(db)
        schema = db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall()
    assets = store(path)
    vrm, archive = model_vrm(), model_zip()
    identity = 'cloud-vrm-' + hashlib.sha256(vrm).hexdigest()
    original = 'cloud-live2d-' + hashlib.sha256(archive).hexdigest()
    assets.put(original, 'Original.zip', archive)
    first = assets.put(identity, 'Public.vrm', vrm)
    assert first['format'] == 'vrm' and first['id'] == identity
    assert assets.put(identity, 'Keep original name', vrm) == first
    assert assets.get(identity) == vrm and store(path).get(identity) == vrm
    assert assets.get('cloud-live2d-' + first['sha256']) is None
    assert assets.get(original) == archive
    with pytest.raises(ValueError):
        assets.put('cloud-live2d-' + first['sha256'], 'Wrong.zip', vrm)
    with closing(sqlite3.connect(path)) as db:
        assert db.execute('SELECT sql FROM sqlite_master ORDER BY name').fetchall() == schema
    assert len(assets.catalog()) == 2


def test_legacy_vrm_without_json_padding_is_bounded_and_accepted_unchanged():
    original = model_vrm()
    size = struct.unpack_from('<I', original, 12)[0]
    chunk = original[20:20 + size].rstrip(b' ')
    content = struct.pack('<4sII', b'glTF', 2, len(original) - size + len(chunk)) + struct.pack('<II', len(chunk), 0x4E4F534A) + chunk + original[20 + size:]
    before = hashlib.sha256(content).hexdigest()
    assert validate_vrm(content) == 'model.vrm'
    assert hashlib.sha256(content).hexdigest() == before
    for broken in (content[:-1], content + b'junk', content[:16] + struct.pack('<I', 0xFFFFFFFF) + content[20:]):
        with pytest.raises(ValueError):
            validate_vrm(broken)


def test_vrm_upload_preview_publish_then_resident_and_old_profile_rollback(models_api):
    client, staff, resident = models_api
    content = model_vrm()
    identity = 'cloud-vrm-' + hashlib.sha256(content).hexdigest()
    url = '/api/v1/service-desk/airi-models/' + identity + '?name=Public.vrm'
    assert client.put(url, headers={**resident, 'Content-Type': 'model/gltf-binary'}, content=content).status_code == 403
    assert client.put(url, headers={**staff, 'Content-Type': 'application/zip'}, content=content).status_code == 415
    reply = client.put(url, headers={**staff, 'Content-Type': 'model/gltf-binary'}, content=content)
    assert reply.status_code == 200, reply.text
    assert reply.json()['format'] == 'vrm'
    target = '/api/v1/resident/airi-models/' + identity
    assert client.get(target, headers=resident).status_code == 403
    assert client.get(target, headers=staff).content == content
    before = client.get('/api/v1/service-desk/presentation', headers=staff).json()
    payload = copy.deepcopy(before)
    payload['expected_revision'] = payload.pop('revision')
    payload['airi']['stage_model'] = identity
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=payload).status_code == 200
    result = client.get(target, headers=resident)
    assert result.status_code == 200 and result.content == content
    assert result.headers['x-model-sha256'] == hashlib.sha256(content).hexdigest()
    assert result.headers['content-type'] == 'model/gltf-binary'
    payload['expected_revision'] += 1
    payload['airi']['stage_model'] = 'cloud-live2d-' + hashlib.sha256(content).hexdigest()
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=payload).status_code == 422
    payload['airi'] = before['airi']
    assert client.put('/api/v1/service-desk/presentation', headers=staff, json=payload).status_code == 200
    assert client.get(target, headers=resident).status_code == 403
    assert client.get(target, headers=staff).content == content
