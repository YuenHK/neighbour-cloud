import json

from local_audio_gateway.model_paths import SENSEVOICE_DIRECTORY, sensevoice_root


def test_notebook_import_is_used_without_inherited_environment(tmp_path):
    assets = tmp_path/'resources/Models/speech'/SENSEVOICE_DIRECTORY
    assets.mkdir(parents=True)
    for name in ('model.int8.onnx','tokens.txt'):
        (assets/name).write_bytes(b'synthetic')
    (tmp_path/'IMPORT-RECEIPT.json').write_text(json.dumps({'resources':str(tmp_path/'resources')}))
    assert sensevoice_root(tmp_path,{}) == assets
    assert sensevoice_root(tmp_path,{'ZHIWEI_SENSEVOICE_ROOT':str(tmp_path/'explicit')}) == tmp_path/'explicit'


def test_incomplete_or_invalid_import_never_selects_another_user(tmp_path):
    (tmp_path/'IMPORT-RECEIPT.json').write_text('{invalid')
    assert sensevoice_root(tmp_path,{}) == tmp_path/'models/speech'/SENSEVOICE_DIRECTORY
