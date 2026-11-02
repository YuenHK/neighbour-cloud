import io
import json
import struct
import zipfile

import pytest
from test_cloud_avatar_assets import model_zip

from deploy.cloud.avatar_assets import validate_archive
from deploy.cloud.avatar_prepare import prepare_archive, zip_bound


def packed(files):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', zipfile.ZIP_DEFLATED) as target:
        for name, data in files.items():
            target.writestr(name, data)
    return result.getvalue()


def test_repair_nested_paths_case_and_extra_editor_sound_keeps_original_mesh_texture_and_terms():
    raw = model_zip()
    with zipfile.ZipFile(io.BytesIO(raw)) as original:
        config = json.loads(original.read('avatar.model3.json'))
        config['FileReferences']['Moc'] = 'BODY.moc3'
        config['FileReferences']['Textures'] = ['..\\Textures\\TEXTURE.png']
        config['FileReferences']['Motions'] = {'Idle': [{'File': 'idle.motion3.json', 'Sound': 'voice.wav'}]}
        content = packed({'pack/runtime/avatar.model3.json': json.dumps(config).encode(),
                          'pack/runtime/body.moc3': original.read('body.moc3'),
                          'pack/Textures/texture.png': original.read('texture.png'),
                          'pack/runtime/idle.motion3.json': b'{}', 'pack/voice.wav': b'RIFF',
                          'pack/editor/model.cmo3': b'not runtime', 'LICENSE.txt': b'Creator NC attribution'})
        result = prepare_archive(content)
        assert result['original_bytes'] == len(content)
        assert validate_archive(result['content']) == 'model.model3.json'
        with zipfile.ZipFile(io.BytesIO(result['content'])) as output:
            prepared = json.loads(output.read('model.model3.json'))
            refs = prepared['FileReferences']
            assert output.read(refs['Moc']) == original.read('body.moc3')
            assert output.read(refs['Textures'][0]) == original.read('texture.png')
            assert 'Sound' not in refs['Motions']['Idle'][0]
            assert prepared['Neighbour']['fit'] == 'visible-contain-v1'
            assert any(output.read(name) == b'Creator NC attribution' for name in output.namelist())
            assert not any(name.endswith(('.wav', '.cmo3')) for name in output.namelist())
        assert prepare_archive(content)['content'] == result['content']


def test_multiple_models_require_explicit_selection_and_missing_reference_cannot_be_invented():
    with zipfile.ZipFile(io.BytesIO(model_zip())) as original:
        files = {name: original.read(name) for name in original.namelist()}
    files['second.model3.json'] = files['avatar.model3.json']
    content = packed(files)
    assert prepare_archive(content) == {'models': ['avatar.model3.json', 'second.model3.json']}
    assert 'content' in prepare_archive(content, 'second.model3.json')
    with pytest.raises(ValueError):
        prepare_archive(content, 'arbitrary.model3.json')
    with pytest.raises(ValueError, match='不存在'):
        prepare_archive(model_zip(refs={'Moc': 'missing.moc3', 'Textures': ['texture.png']}))


def test_preflight_rejects_large_central_directory_before_zipfile_allocation_and_paths():
    content = bytearray(model_zip())
    eocd = content.rfind(b'PK\x05\x06')
    struct.pack_into('<H', content, eocd + 10, 60000)
    with pytest.raises(ValueError, match='目錄'):
        zip_bound(bytes(content))
    for extra in ({'../unsafe.txt': b'x'}, {'TEXTURE.png': b'duplicate'}, {'old.model.json': b'{}'}):
        candidate = model_zip(extra)
        if '../unsafe.txt' in extra or 'TEXTURE.png' in extra:
            with pytest.raises(ValueError):
                prepare_archive(candidate)
    with pytest.raises(ValueError, match='欠缺'):
        prepare_archive(packed({'avatar.cmo3': b'editor only'}))
