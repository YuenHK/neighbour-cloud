import copy
import hashlib
import io
import json
import struct
import zlib

import pytest
from PIL import Image

from deploy.cloud import reviewed_vrm_prepare as prepare
from deploy.cloud.avatar_vrm import REQUIRED_BONES, validate_vrm


def picture(size=(2048, 1024), mode='RGBA', kind='PNG'):
    output = io.BytesIO()
    color = (30, 90, 180, 125) if mode == 'RGBA' else (30, 90, 180)
    Image.new(mode, size, color).save(output, format=kind)
    return output.getvalue()


def pack(doc, binary):
    doc = copy.deepcopy(doc)
    doc['buffers'][0]['byteLength'] = len(binary)
    header = json.dumps(doc, ensure_ascii=False, separators=(',', ':')).encode()
    header += b' ' * ((-len(header)) % 4)
    binary = bytes(binary) + b'\0' * ((-len(binary)) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(header) + len(binary))
            + struct.pack('<II', len(header), 0x4E4F534A) + header
            + struct.pack('<II', len(binary), 0x004E4942) + binary)


def unpack(raw):
    size = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20 + size])
    return doc, raw[28 + size:]


def fixture(images=None):
    images = images if images is not None else [picture()]
    # A genuine triangle view must survive exactly; image bytes live elsewhere.
    geometry = struct.pack('<9f', 0, 0, 0, 1, 0, 0, 0, 1, 0)
    binary = bytearray(geometry)
    views = [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(geometry), 'target': 34962}]
    rows = []
    for value in images:
        binary.extend(b'\0' * ((-len(binary)) % 4))
        views.append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': len(value)})
        rows.append({'bufferView': len(views) - 1,
                     'mimeType': 'image/png' if value.startswith(b'\x89PNG') else 'image/jpeg'})
        binary.extend(value)
    bones = sorted(REQUIRED_BONES)
    doc = {
        'asset': {'version': '2.0'}, 'buffers': [{'byteLength': len(binary)}],
        'bufferViews': views, 'images': rows,
        'textures': [{'source': index} for index in range(len(images))],
        'materials': [{'name': 'keep-original', 'doubleSided': True}],
        'accessors': [{'bufferView': 0, 'componentType': 5126, 'count': 3, 'type': 'VEC3'}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'material': 0}]}],
        'nodes': [{'name': bone} for bone in bones], 'skins': [],
        'extensions': {'VRM': {
            'humanoid': {'humanBones': [{'bone': bone, 'node': i} for i, bone in enumerate(bones)]},
            'meta': {'author': 'Original Synthetic Artist', 'licenseName': 'CC_BY',
                     'otherLicenseUrl': 'https://example.invalid/original-licence'},
            'blendShapeMaster': {'blendShapeGroups': [{'name': 'aa', 'binds': []}]},
        }},
    }
    return pack(doc, binary)


def reject(raw, match=None):
    with pytest.raises(ValueError, match=match):
        prepare.prepare_vrm(raw, expected_output_sha256='0' * 64)


def test_image_only_reduction_keeps_real_geometry_rig_material_and_licence():
    raw = fixture()
    original, old_binary = unpack(raw)
    built = prepare._prepare_vrm(raw)
    # The final digest gate is mandatory and independently checked by callers.
    output = prepare.prepare_vrm(raw, expected_output_sha256=hashlib.sha256(built).hexdigest())
    doc, binary = unpack(output)
    assert validate_vrm(output) == 'model.vrm'
    for field in ('nodes', 'skins', 'meshes', 'accessors', 'textures', 'materials', 'extensions'):
        assert doc[field] == original[field]
    old_view, new_view = original['bufferViews'][0], doc['bufferViews'][0]
    assert binary[new_view['byteOffset']:new_view['byteOffset'] + new_view['byteLength']] == old_binary[
        old_view['byteOffset']:old_view['byteOffset'] + old_view['byteLength']]
    view = doc['bufferViews'][1]
    with Image.open(io.BytesIO(binary[view['byteOffset']:view['byteOffset'] + view['byteLength']])) as image:
        assert image.size == (1024, 512)
        assert image.getpixel((100, 100))[3] == 125
    assert raw == fixture()  # The input was never modified.
    assert prepare._prepare_vrm(raw) == output
    assert len(output) <= 32 * 1024 * 1024


def test_small_jpeg_is_fully_decoded_but_retained_byte_for_byte():
    image = picture((24, 24), 'RGB', 'JPEG')
    doc, binary = unpack(prepare._prepare_vrm(fixture([image])))
    view = doc['bufferViews'][1]
    assert doc['images'][0]['mimeType'] == 'image/jpeg'
    assert binary[view['byteOffset']:view['byteOffset'] + view['byteLength']] == image


def test_large_jpeg_becomes_png_without_changing_texture_material_binding():
    raw = fixture([picture((2048, 1024), 'RGB', 'JPEG')])
    before, _ = unpack(raw)
    doc, binary = unpack(prepare._prepare_vrm(raw))
    assert doc['textures'] == before['textures'] and doc['materials'] == before['materials']
    assert doc['images'][0]['mimeType'] == 'image/png'
    view = doc['bufferViews'][1]
    assert binary[view['byteOffset']:view['byteOffset'] + 8] == b'\x89PNG\r\n\x1a\n'


@pytest.mark.parametrize('digest', ['', 'A' * 64, 'g' * 64, None])
def test_digest_and_recipe_cannot_be_omitted_or_loosely_parsed(digest):
    reject = {'expected_output_sha256': digest}
    with pytest.raises(ValueError):
        prepare.prepare_vrm(fixture(), **reject)
    with pytest.raises(ValueError):
        prepare.prepare_vrm(fixture(), expected_output_sha256='0' * 64, recipe='latest')


def test_wrong_output_digest_never_returns_content():
    reject(fixture(), '摘要不同')


def test_wrong_pillow_version_fails_before_any_image_decode(monkeypatch):
    monkeypatch.setattr(Image, '__version__', '11.3.1')
    monkeypatch.setattr(Image, 'open', lambda *a, **k: pytest.fail('must not decode'))
    reject(fixture(images=[]), '版本不同')


@pytest.mark.parametrize('change', [
    lambda doc: doc['buffers'][0].update(uri='https://remote.invalid/model.bin'),
    lambda doc: doc['images'][0].update(uri='data:image/png;base64,nope'),
    lambda doc: doc['extensions'].update(unreviewed={'uri': 'https://remote.invalid/file'}),
    lambda doc: doc['bufferViews'][1].update(buffer=False),
    lambda doc: doc['bufferViews'][1].update(byteLength=999999999),
    lambda doc: doc['images'][0].update(mimeType='image/webp'),
    lambda doc: doc['images'][0].update(mimeType='image/jpeg'),
    lambda doc: doc['images'][0].update(bufferView=True),
    lambda doc: doc.update(images=doc['images'] * 65),
    lambda doc: doc.update(bufferViews=doc['bufferViews'] * 2049),
])
def test_malformed_external_overbound_or_mismatched_resources_fail_closed(change):
    doc, binary = unpack(fixture())
    change(doc)
    reject(pack(doc, binary))


@pytest.mark.parametrize('sparse', [False, True])
def test_image_accessor_alias_is_rejected_even_for_sparse_indices(sparse):
    doc, binary = unpack(fixture())
    if sparse:
        doc['accessors'][0]['sparse'] = {'count': 1, 'indices': {'bufferView': 1, 'componentType': 5123},
                                         'values': {'bufferView': 0}}
    else:
        doc['accessors'][0]['bufferView'] = 1
    reject(pack(doc, binary), '共用')


@pytest.mark.parametrize('reference', [False, -1, 99999, []])
def test_invalid_nonimage_buffer_references_are_rejected(reference):
    doc, binary = unpack(fixture())
    doc['accessors'][0]['bufferView'] = reference
    reject(pack(doc, binary), '引用')


def test_overlapping_separate_buffer_view_and_duplicate_image_views_are_rejected():
    doc, binary = unpack(fixture())
    doc['bufferViews'][0]['byteOffset'] = doc['bufferViews'][1]['byteOffset'] + 1
    reject(pack(doc, binary), '重疊')
    doc, binary = unpack(fixture())
    doc['images'].append(copy.deepcopy(doc['images'][0]))
    reject(pack(doc, binary), '別名')


def header_dimensions(png, width, height):
    raw = bytearray(png)
    struct.pack_into('>II', raw, 16, width, height)
    struct.pack_into('>I', raw, 29, zlib.crc32(raw[12:29]))
    return bytes(raw)


def test_single_and_aggregate_pixel_bounds_are_checked_before_pixel_decode(monkeypatch):
    image = picture((8, 8))
    # Header-only huge images avoid allocating giant buffers in this regression.
    raw = fixture([header_dimensions(image, 6001, 4200)])
    reject(raw, '大小')
    raw = fixture([header_dimensions(image, 6000, 4000)] * 6)
    monkeypatch.setattr(prepare, '_resize_image', lambda data: pytest.fail('must check aggregate first'))
    reject(raw, '總像素')


def test_animated_png_and_truncated_small_texture_are_rejected():
    buffer = io.BytesIO()
    first = Image.new('RGBA', (8, 8), 'red')
    second = Image.new('RGBA', (8, 8), 'blue')
    first.save(buffer, format='PNG', save_all=True, append_images=[second], duration=100)
    reject(fixture([buffer.getvalue()]), '影格')
    reject(fixture([picture((20, 20))[:60]]))


def test_exif_rotation_is_not_silently_applied_to_a_texture():
    output = io.BytesIO()
    exif = Image.Exif()
    exif[274] = 6
    Image.new('RGB', (32, 16), 'red').save(output, format='JPEG', exif=exif)
    reject(fixture([output.getvalue()]), '方向')


def test_input_json_and_output_bounds_are_enforced(monkeypatch):
    reject(b'x' * (prepare.MAX_INPUT + 1), '64 MB')
    doc, binary = unpack(fixture())
    doc['oversized'] = 'x' * prepare.MAX_JSON
    reject(pack(doc, binary), '分段')
    # Check the final container bound, not only the size of encoded images.
    monkeypatch.setattr(prepare, 'MAX_BYTES', 1000)
    reject(fixture([picture((8, 8))]), '32 MB')


def test_nonfinite_and_duplicate_json_fields_are_rejected():
    doc, binary = unpack(fixture())
    doc['bad'] = float('nan')
    reject(pack(doc, binary), '數字')
    raw = fixture()
    size = struct.unpack_from('<I', raw, 12)[0]
    json_bytes = raw[20:20 + size].rstrip()
    changed = json_bytes[:-1] + b',"asset":{"version":"2.0"}}'
    changed += b' ' * ((-len(changed)) % 4)
    rest = raw[20 + size:]
    duplicate = (struct.pack('<4sII', b'glTF', 2, 20 + len(changed) + len(rest))
                 + struct.pack('<II', len(changed), 0x4E4F534A) + changed + rest)
    reject(duplicate, '重複')


def test_unknown_extra_glb_chunks_and_false_lengths_are_rejected():
    raw = fixture()
    extra = raw + struct.pack('<II', 0, 123)
    extra = extra[:8] + struct.pack('<I', len(extra)) + extra[12:]
    reject(extra, '分段')
    reject(raw[:-1], '完整')
