"""Validate bounded, self-contained VRM GLBs before durable shared publishing."""
import io
import json
import math
import struct

from PIL import Image

MAX_BYTES = 32 * 1024 * 1024
REQUIRED_BONES = {'hips', 'spine', 'head', 'leftUpperArm', 'leftLowerArm', 'leftHand',
                  'rightUpperArm', 'rightLowerArm', 'rightHand', 'leftUpperLeg', 'leftLowerLeg',
                  'leftFoot', 'rightUpperLeg', 'rightLowerLeg', 'rightFoot'}


def integer(value, upper):
    return type(value) is int and 0 <= value < upper


def validate_vrm(content):
    """No external images/buffers, executables, network fetches or model changes."""
    try:
        if not isinstance(content, bytes) or not 28 <= len(content) <= MAX_BYTES:
            raise ValueError('VRM 檔案最大為 32 MB。')
        if struct.unpack_from('<4sII', content) != (b'glTF', 2, len(content)):
            raise ValueError('需要完整的 VRM／GLB 2 模型。')
        offset, chunks = 12, []
        while offset < len(content):
            size, kind = struct.unpack_from('<II', content, offset)
            # Older VRM exporters omit JSON-chunk padding. AIRI's GLTFLoader
            # reads explicit lengths and accepts these unchanged files too.
            if offset + 8 + size > len(content):
                raise ValueError('VRM 檔案分段不完整。')
            chunks.append((kind, content[offset + 8:offset + 8 + size]))
            offset += 8 + size
        if [row[0] for row in chunks] != [0x4E4F534A, 0x004E4942] or len(chunks[0][1]) > 4 * 1024 * 1024:
            raise ValueError('VRM 必須包含一份設定及內嵌模型資料。')
        def invalid_constant(value):
            raise ValueError('invalid model number')
        doc = json.loads(chunks[0][1], parse_constant=invalid_constant)
        binary = chunks[1][1]
        if doc.get('asset', {}).get('version') != '2.0':
            raise ValueError('需要 GLB 2 模型。')
        buffers = doc.get('buffers', [])
        if (len(buffers) != 1 or 'uri' in buffers[0] or type(buffers[0].get('byteLength')) is not int
                or not 0 < buffers[0]['byteLength'] <= len(binary)
                or len(binary) - buffers[0]['byteLength'] > 3):
            raise ValueError('請使用資料完整內嵌的 VRM，不能引用外部檔案。')
        views = doc.get('bufferViews', [])
        if not isinstance(views, list) or len(views) > 10000:
            raise ValueError('模型資料分段過多。')
        for view in views:
            start, size = view.get('byteOffset', 0), view.get('byteLength')
            if (view.get('buffer') != 0 or type(start) is not int or type(size) is not int
                    or start < 0 or size < 0 or start + size > buffers[0]['byteLength']):
                raise ValueError('模型資料範圍不正確。')
        nodes = doc.get('nodes', [])
        if not isinstance(nodes, list) or not 1 <= len(nodes) <= 4096:
            raise ValueError('模型骨架太大或不存在。')
        edges = {}
        for index, node in enumerate(nodes):
            children = node.get('children', [])
            if not isinstance(children, list) or any(not integer(child, len(nodes)) for child in children):
                raise ValueError('模型骨架引用不正確。')
            edges[index] = children
            for field, length in (('matrix', 16), ('translation', 3), ('rotation', 4), ('scale', 3)):
                if field in node and (len(node[field]) != length or any(
                        type(value) not in (int, float) or not math.isfinite(value) or abs(value) > 1e6 for value in node[field])):
                    raise ValueError('模型位置或比例不正確。')
        visited, active = set(), set()
        def visit(index, depth=0):
            if index in active or depth > 128:
                raise ValueError('模型骨架有循環或太深。')
            if index in visited:
                return
            active.add(index)
            for child in edges[index]:
                visit(child, depth + 1)
            active.remove(index)
            visited.add(index)
        for index in edges:
            visit(index)
        extensions = doc.get('extensions', {})
        if 'VRM' in extensions:
            vrm = extensions['VRM']
            bones = vrm.get('humanoid', {}).get('humanBones', [])
            names = [row['bone'] for row in bones]
            indices = [row['node'] for row in bones]
        elif extensions.get('VRMC_vrm', {}).get('specVersion') == '1.0':
            vrm = extensions['VRMC_vrm']
            bones = vrm.get('humanoid', {}).get('humanBones', {})
            names = list(bones)
            indices = [row['node'] for row in bones.values()]
        else:
            raise ValueError('需要 VRM 0.x 或 1.0 人形模型。')
        if (not REQUIRED_BONES.issubset(names) or len(set(names)) != len(names)
                or any(not integer(index, len(nodes)) for index in indices)):
            raise ValueError('VRM 缺少必要的人形骨架。')
        if not isinstance(doc.get('meshes'), list) or not 1 <= len(doc['meshes']) <= 512:
            raise ValueError('VRM 缺少可顯示的模型。')
        images, pixels = doc.get('images', []), 0
        if not isinstance(images, list) or len(images) > 64:
            raise ValueError('模型貼圖過多。')
        for image in images:
            if 'uri' in image or not integer(image.get('bufferView'), len(views)):
                raise ValueError('請使用內嵌貼圖，不可引用外部網址。')
            view = views[image['bufferView']]
            start = view.get('byteOffset', 0)
            with Image.open(io.BytesIO(binary[start:start + view['byteLength']])) as picture:
                if not 0 < picture.width <= 8192 or not 0 < picture.height <= 8192:
                    raise ValueError('模型貼圖尺寸太大。')
                pixels += picture.width * picture.height
                picture.verify()
        if pixels > 32 * 1024 * 1024:
            raise ValueError('模型貼圖總尺寸太大。')
        return 'model.vrm'
    except (KeyError, TypeError, AttributeError, IndexError, struct.error, UnicodeError, OSError,
            RecursionError, json.JSONDecodeError, Image.DecompressionBombError) as error:
        raise ValueError('VRM 未能核對，原有模型保留。') from error
