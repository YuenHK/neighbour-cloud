"""Fixed, bounded image-only recipe for separately reviewed VRM originals.

This is not a generic user-upload converter or a licence grant. The importer must
verify the original bytes first; publication additionally requires the recorded
output digest. No geometry, rig, expressions, materials or licence fields change.
"""
import hashlib
import io
import json
import math
import re
import struct
import warnings

from PIL import Image

from deploy.cloud.avatar_vrm import MAX_BYTES, validate_vrm

RECIPE_ID = 'vrm-png1024-pillow11.3.0-v1'
PILLOW_VERSION = '11.3.0'
MAX_INPUT = 64 * 1024 * 1024
MAX_JSON = 4 * 1024 * 1024
MAX_VIEWS = 4096
MAX_IMAGES = 64
MAX_IMAGE_PIXELS = 24_000_000
MAX_TOTAL_PIXELS = 128_000_000
MAX_EDGE = 1024
_DIGEST = re.compile(r'[0-9a-f]{64}\Z')
_JSON_CHUNK, _BIN_CHUNK = 0x4E4F534A, 0x004E4942


def _integer(value, minimum=0):
    return type(value) is int and value >= minimum


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('重複的模型設定欄位。')
        result[key] = value
    return result


def _bad_number(_value):
    raise ValueError('模型設定含無效數字。')


def _check_tree(doc):
    pending, nodes = [(doc, 0)], 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if depth > 64 or nodes > 250000:
            raise ValueError('模型設定太複雜。')
        if isinstance(value, dict):
            if 'uri' in value:
                raise ValueError('只可處理完全內嵌的模型。')
            pending.extend((child, depth + 1) for child in value.values())
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, float) and not math.isfinite(value):
            raise ValueError('模型設定含無效數字。')


def _parse(content):
    if not isinstance(content, bytes) or not 28 <= len(content) <= MAX_INPUT:
        raise ValueError('待處理的原模型必須小於 64 MB。')
    if struct.unpack_from('<4sII', content) != (b'glTF', 2, len(content)):
        raise ValueError('原模型不是完整的 GLB 2。')
    offset, chunks = 12, []
    while offset < len(content):
        if len(chunks) >= 2 or offset + 8 > len(content):
            raise ValueError('原模型分段不正確。')
        size, kind = struct.unpack_from('<II', content, offset)
        if offset + 8 + size > len(content) or (kind == _JSON_CHUNK and size > MAX_JSON):
            raise ValueError('原模型分段過大或不完整。')
        chunks.append((kind, offset + 8, size))
        offset += 8 + size
    if [chunk[0] for chunk in chunks] != [_JSON_CHUNK, _BIN_CHUNK]:
        raise ValueError('原模型需要一份設定及一份內嵌資料。')
    start, size = chunks[0][1:]
    doc = json.loads(content[start:start + size], object_pairs_hook=_pairs, parse_constant=_bad_number)
    _check_tree(doc)
    if not isinstance(doc, dict) or doc.get('asset', {}).get('version') != '2.0':
        raise ValueError('原模型設定不正確。')
    buffers = doc.get('buffers')
    start, size = chunks[1][1:]
    if (not isinstance(buffers, list) or len(buffers) != 1 or not isinstance(buffers[0], dict)
            or not _integer(buffers[0].get('byteLength'), 1)
            or not 0 <= size - buffers[0]['byteLength'] <= 3):
        raise ValueError('原模型的內嵌資料範圍不正確。')
    binary = memoryview(content)[start:start + buffers[0]['byteLength']]
    views = doc.get('bufferViews')
    if not isinstance(views, list) or not 1 <= len(views) <= MAX_VIEWS:
        raise ValueError('原模型資料分段過多。')
    for view in views:
        if (not isinstance(view, dict) or type(view.get('buffer')) is not int or view['buffer'] != 0
                or not _integer(view.get('byteOffset', 0)) or not _integer(view.get('byteLength'), 1)
                or view.get('byteOffset', 0) + view['byteLength'] > len(binary)):
            raise ValueError('原模型資料分段越界。')
    return doc, binary


def _image_views(doc):
    images, views = doc.get('images', []), doc['bufferViews']
    if not isinstance(images, list) or len(images) > MAX_IMAGES:
        raise ValueError('原模型貼圖過多。')
    indices = set()
    for image in images:
        if (not isinstance(image, dict) or not _integer(image.get('bufferView'))
                or image['bufferView'] >= len(views) or image.get('mimeType') not in ('image/png', 'image/jpeg')):
            raise ValueError('貼圖必須是內嵌 PNG 或 JPEG。')
        index = image['bufferView']
        if index in indices or 'byteStride' in views[index] or 'target' in views[index]:
            raise ValueError('貼圖資料不得別名或兼作幾何。')
        indices.add(index)

    # Any non-image consumer of an image view is rejected, including sparse
    # accessors and extension bufferView references, not just direct accessors.
    pending = [value for key, value in doc.items() if key not in ('images', 'bufferViews')]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if 'bufferView' in value:
                reference = value['bufferView']
                if not _integer(reference) or reference >= len(views):
                    raise ValueError('模型的內嵌資料引用不正確。')
                if reference in indices:
                    raise ValueError('貼圖資料不得與幾何或其他資料共用。')
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    intervals = [(view.get('byteOffset', 0), view.get('byteOffset', 0) + view['byteLength']) for view in views]
    for index in indices:
        left, right = intervals[index]
        if any(index != other and left < end and begin < right for other, (begin, end) in enumerate(intervals)):
            raise ValueError('貼圖資料範圍不得與其他分段重疊。')
    return images, indices


def _image_bytes(binary, view):
    start = view.get('byteOffset', 0)
    return binary[start:start + view['byteLength']]


def _inspect_images(images, views, binary):
    total = 0
    for image in images:
        with Image.open(io.BytesIO(_image_bytes(binary, views[image['bufferView']])), formats=('PNG', 'JPEG')) as picture:
            expected = 'image/png' if picture.format == 'PNG' else 'image/jpeg'
            if (image['mimeType'] != expected or getattr(picture, 'n_frames', 1) != 1
                    or not 0 < picture.width * picture.height <= MAX_IMAGE_PIXELS):
                raise ValueError('貼圖大小、方向、格式或影格不適用。')
            total += picture.width * picture.height
            if total > MAX_TOTAL_PIXELS:
                raise ValueError('原模型貼圖總像素過大。')


def _resize_image(data):
    with Image.open(io.BytesIO(data), formats=('PNG', 'JPEG')) as picture:
        # Fully decode even retained images; invalid/truncated tails must not be
        # accepted merely because the image header advertised a small texture.
        picture.load()
        # PNG getexif() itself loads pixels. Keep it after the complete header
        # budget pass, rather than accidentally decoding during that pass.
        if picture.getexif().get(274, 1) != 1:
            raise ValueError('貼圖方向不適用，原模型保留。')
        if max(picture.size) <= MAX_EDGE:
            return data, False
        picture.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
        mode = 'RGBA' if 'A' in picture.getbands() or 'transparency' in picture.info else 'RGB'
        with picture.convert(mode) as resized:
            resized.info.clear()
            output = io.BytesIO()
            resized.save(output, format='PNG', optimize=True, compress_level=9)
        return output.getvalue(), True


def _prepare_vrm(content):
    """Internal recipe builder for pinned-manifest review; never auto-publish."""
    if Image.__version__ != PILLOW_VERSION:
        raise ValueError('貼圖處理程式版本不同，原模型保留。')
    doc, binary = _parse(content)
    images, image_indices = _image_views(doc)
    views = doc['bufferViews']
    with warnings.catch_warnings():
        warnings.simplefilter('error', Image.DecompressionBombWarning)
        _inspect_images(images, views, binary)
        image_by_view = {row['bufferView']: row for row in images}
        prepared = bytearray()
        for index, view in enumerate(views):
            data = _image_bytes(binary, view)
            if index in image_indices:
                data, changed = _resize_image(data)
                if changed:
                    image_by_view[index]['mimeType'] = 'image/png'
            padding = (-len(prepared)) % 4
            if len(prepared) + padding + len(data) > MAX_BYTES:
                raise ValueError('處理後模型仍超過 32 MB，原模型保留。')
            prepared.extend(b'\x00' * padding)
            view['byteOffset'], view['byteLength'] = len(prepared), len(data)
            prepared.extend(data)
    doc['buffers'][0]['byteLength'] = len(prepared)
    encoded = json.dumps(doc, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
    if len(encoded) > MAX_JSON:
        raise ValueError('處理後設定超出上限。')
    encoded += b' ' * ((-len(encoded)) % 4)
    prepared.extend(b'\x00' * ((-len(prepared)) % 4))
    length = 28 + len(encoded) + len(prepared)
    if length > MAX_BYTES:
        raise ValueError('處理後模型仍超過 32 MB，原模型保留。')
    output = (struct.pack('<4sII', b'glTF', 2, length)
              + struct.pack('<II', len(encoded), _JSON_CHUNK) + encoded
              + struct.pack('<II', len(prepared), _BIN_CHUNK) + prepared)
    validate_vrm(output)
    return output


def prepare_vrm(content, *, expected_output_sha256, recipe=RECIPE_ID):
    """Prepare a reviewed original, only returning its pre-approved exact hash."""
    if recipe != RECIPE_ID or not isinstance(expected_output_sha256, str) or not _DIGEST.fullmatch(expected_output_sha256):
        raise ValueError('模型處理配方或核准摘要不正確。')
    try:
        output = _prepare_vrm(content)
        if hashlib.sha256(output).hexdigest() != expected_output_sha256:
            raise ValueError('處理後模型摘要不同，原模型保留。')
        return output
    except (KeyError, TypeError, AttributeError, IndexError, struct.error, UnicodeError,
            OSError, RecursionError, OverflowError, json.JSONDecodeError,
            Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise ValueError('模型未能按核准配方處理，原模型保留。') from error
