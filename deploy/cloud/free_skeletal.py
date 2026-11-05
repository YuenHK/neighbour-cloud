"""Bounded Rigby JSON bundles. No Esoteric runtime, conversion, fetches or database writes.

This is a deliberately distinct, reviewed free renderer format. It accepts region
attachments and unweighted meshes only, not arbitrary Spine archives or binaries.
The author/licence metadata is retained; a format validator cannot grant asset rights.
"""
import io
import json
import math
import re
import stat
import zipfile

from PIL import Image

from deploy.cloud.avatar_prepare import zip_bound

FORMAT = 'rigby-json-zip/v1'
ENTRYPOINT = 'model.rigby.json'
MAX_JSON = 3 * 1024 * 1024
MAX_ATLAS = 64 * 1024
MAX_TEXTURE = 16 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024
FORBIDDEN = {'__proto__', 'prototype', 'constructor'}


def fail(reason):
    raise ValueError('免費骨架模型：' + reason)


def safe_path(value):
    return (isinstance(value, str) and 0 < len(value) <= 240
            and not re.search(r'[\\:%?#\x00-\x20\x7f]', value) and not value.startswith('/')
            and all(part not in ('', '.', '..') for part in value.split('/')))


def name_ok(value):
    return (isinstance(value, str) and 0 < len(value) <= 160 and value not in FORBIDDEN
            and not re.search(r'[\x00-\x1f\x7f]', value))


def tree_bounds(root):
    stack, count = [(root, 0)], 0
    while stack:
        value, depth = stack.pop()
        count += 1
        if count > 100000 or depth > 32:
            fail('內容過大或層次過深。')
        if type(value) in (int, float) and (not math.isfinite(value) or abs(value) > 1e7):
            fail('數值無效或超出範圍。')
        if isinstance(value, str) and len(value) > 4096:
            fail('文字欄位過長。')
        if isinstance(value, list):
            if len(value) > 20000:
                fail('資料陣列過大。')
            stack.extend((item, depth + 1) for item in value)
        elif isinstance(value, dict):
            if any(not name_ok(key) for key in value):
                fail('欄位名稱不安全。')
            stack.extend((item, depth + 1) for item in value.values())


def read_json(raw, limit):
    if len(raw) > limit:
        fail('設定檔太大。')

    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                fail('JSON 有重複欄位。')
            result[key] = value
        return result

    def constant(_value):
        fail('JSON 包含無效數字。')
    result = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=pairs, parse_constant=constant)
    tree_bounds(result)
    return result


def numeric_fields(item, fields):
    if any(key in item and type(item[key]) not in (int, float) for key in fields):
        fail('數值欄位不可使用文字或空值。')


def names(items, maximum, label):
    if not isinstance(items, list) or not 0 < len(items) <= maximum:
        fail(label + '數量不正確。')
    result = set()
    for item in items:
        if not isinstance(item, dict) or not name_ok(item.get('name')) or item['name'] in result:
            fail(label + '名稱重複或無效。')
        result.add(item['name'])
    return result


def parse_atlas(text):
    pages, page, region = [], None, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            page = region = None
            continue
        if ':' not in line:
            if not safe_path(line):
                fail('貼圖清單不可引用外部或不安全路徑。')
            if page is None:
                page = {'name': line, 'regions': [], 'size': None}
                pages.append(page)
            else:
                region = {'name': line}
                page['regions'].append(region)
            continue
        if page is None:
            fail('貼圖清單格式不正確。')
        key, value = [part.strip() for part in line.split(':', 1)]
        target = region if region is not None else page
        if key in ('size', 'xy', 'bounds', 'orig', 'offset', 'offsets'):
            values = [int(part.strip()) for part in value.split(',')]
            expected = 4 if key in ('bounds', 'offsets') else 2
            if len(values) != expected:
                fail('貼圖尺寸欄位不正確。')
            target[key] = values
        elif key == 'rotate':
            if value not in ('true', 'false', '0', '90'):
                fail('貼圖旋轉格式不支援。')
        elif key not in ('format', 'filter', 'repeat', 'pma', 'index'):
            fail('貼圖清單含有未支援欄位。')
    if not 0 < len(pages) <= 8:
        fail('貼圖頁數不正確。')
    seen_pages, seen_regions, total_pixels = set(), set(), 0
    for item in pages:
        key = item['name'].casefold()
        if key in seen_pages or not item['name'].lower().endswith('.png') or not item['size']:
            fail('貼圖頁名稱重複或不支援。')
        seen_pages.add(key)
        width, height = item['size']
        if not 0 < width <= 8192 or not 0 < height <= 8192 or width * height > MAX_PIXELS:
            fail('貼圖像素過大。')
        total_pixels += width * height
        for region in item['regions']:
            if region['name'] in seen_regions or len(seen_regions) >= 1024:
                fail('貼圖區域重複或過多。')
            seen_regions.add(region['name'])
            bounds = region.get('bounds')
            if bounds is None:
                if 'xy' not in region or 'size' not in region:
                    fail('貼圖區域欠缺尺寸。')
                bounds = region['xy'] + region['size']
            x, y, w, h = bounds
            if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
                fail('貼圖區域超出圖片範圍。')
    if total_pixels > MAX_PIXELS * 2:
        fail('貼圖總像素過大。')
    return pages, seen_regions


def validate_skeleton(doc, regions):
    if (not isinstance(doc, dict) or not isinstance(doc.get('skeleton'), dict)
            or not re.match(r'^(?:3\.8|4\.[23])(?:\.|$)', str(doc['skeleton'].get('spine', '')))):
        fail('請使用 Rigby 匯出的受支援 JSON 格式。')
    for field in ('images', 'audio'):
        if doc['skeleton'].get(field) and not safe_path(doc['skeleton'][field]):
            fail('骨架不可引用外部網址。')
    if any(doc.get(field) for field in ('ik', 'transform', 'path', 'physics', 'constraints', 'events')):
        fail('此免費格式暫不接受約束或音效事件。')
    bone_names = names(doc.get('bones'), 256, '骨架')
    visited = set()
    for bone in doc['bones']:
        numeric_fields(bone, ('x', 'y', 'rotation', 'scaleX', 'scaleY', 'shearX', 'shearY', 'length'))
        if 'parent' in bone and bone['parent'] not in visited:
            fail('骨架父節點不存在、次序不正確或有循環。')
        visited.add(bone['name'])
    slot_names = names(doc.get('slots'), 512, '貼圖插槽')
    for slot in doc['slots']:
        if slot.get('bone') not in bone_names or (slot.get('attachment') is not None and not name_ok(slot['attachment'])):
            fail('貼圖插槽引用不正確。')
    skins = doc.get('skins', {})
    if isinstance(skins, dict):
        skins = [{'name': key, 'attachments': value} for key, value in skins.items()]
    if not isinstance(skins, list) or not 0 < len(skins) <= 32:
        fail('皮膚數量不正確。')
    skin_names, attachments, count = set(), {}, 0
    for skin in skins:
        if (not isinstance(skin, dict) or not name_ok(skin.get('name')) or skin['name'] in skin_names
                or not isinstance(skin.get('attachments'), dict)):
            fail('皮膚格式不正確或名稱重複。')
        skin_names.add(skin['name'])
        for slot, values in skin['attachments'].items():
            if slot not in slot_names or not isinstance(values, dict):
                fail('皮膚引用不存在的插槽。')
            for key, value in values.items():
                count += 1
                if not name_ok(key) or count > 2048 or not isinstance(value, dict):
                    fail('皮膚貼圖過多或無效。')
                numeric_fields(value, ('x', 'y', 'rotation', 'scaleX', 'scaleY', 'width', 'height', 'hull'))
                image = value.get('path', value.get('name', key))
                if not safe_path(image) or image not in regions:
                    fail('貼圖區域遺失或包含外部網址。')
                kind = value.get('type', 'region')
                if kind == 'region':
                    if not 0 < value.get('width', 0) <= 8192 or not 0 < value.get('height', 0) <= 8192:
                        fail('貼圖區域尺寸不正確。')
                elif kind == 'mesh':
                    uvs, vertices, triangles = value.get('uvs'), value.get('vertices'), value.get('triangles')
                    if (not isinstance(uvs, list) or not 6 <= len(uvs) <= 8192 or len(uvs) % 2
                            or any(type(number) not in (int, float) or not 0 <= number <= 1 for number in uvs)
                            or not isinstance(vertices, list) or len(vertices) != len(uvs)
                            or any(type(number) not in (int, float) for number in vertices)
                            or not isinstance(triangles, list) or not 0 < len(triangles) <= 12288 or len(triangles) % 3
                            or any(type(number) is not int or not 0 <= number < len(uvs) // 2 for number in triangles)):
                        fail('網格不完整、過大或有尚未支援的權重。')
                else:
                    fail('此免費格式只接受區域及無權重網格。')
                if value.get('sequence'):
                    fail('此免費格式暫不接受圖片序列。')
                attachments.setdefault(slot, set()).add(key)
    for slot in doc['slots']:
        if slot.get('attachment') is not None and slot['attachment'] not in attachments.get(slot['name'], set()):
            fail('預設貼圖沒有對應皮膚。')
    animations = doc.get('animations', {})
    if not isinstance(animations, dict) or len(animations) > 64:
        fail('動作清單不正確。')
    key_count = 0
    channels = {'bones': {'rotate', 'translate', 'translatex', 'translatey', 'scale', 'scalex', 'scaley', 'shear', 'shearx', 'sheary'},
                'slots': {'attachment', 'color', 'rgba', 'rgb', 'alpha', 'twoColor', 'rgba2', 'rgb2'}}
    for animation_name, animation in animations.items():
        if (not name_ok(animation_name) or not isinstance(animation, dict)
                or set(animation) - {'bones', 'slots'}):
            fail('此免費格式暫不接受變形、事件或約束動作。')
        for field, references in (('bones', bone_names), ('slots', slot_names)):
            if not isinstance(animation.get(field, {}), dict):
                fail('動作骨架格式不正確。')
            for target, timelines in animation.get(field, {}).items():
                if target not in references or not isinstance(timelines, dict):
                    fail('動作引用不存在的骨架或貼圖。')
                for channel, keys in timelines.items():
                    if channel not in channels[field] or not isinstance(keys, list):
                        fail('動作類型尚未支援。')
                    previous = -1
                    for key in keys:
                        if not isinstance(key, dict):
                            fail('動作關鍵點不正確。')
                        numeric_fields(key, ('time', 'value', 'angle', 'x', 'y', 'c2', 'c3', 'c4'))
                        stamped = key.get('time', 0)
                        if not 0 <= stamped <= 120 or stamped <= previous:
                            fail('動作時間順序或長度不正確。')
                        previous = stamped
                        curve = key.get('curve', 'linear')
                        if curve not in ('linear', 'stepped') and not (
                                isinstance(curve, list) and len(curve) == 4
                                and all(type(number) in (int, float) for number in curve)):
                            fail('動作曲線格式不正確。')
                        if (field == 'slots' and channel == 'attachment' and key.get('name') is not None
                                and key['name'] not in attachments.get(target, set())):
                            fail('動作引用不存在的皮膚貼圖。')
                        key_count += 1
                        if key_count > 20000:
                            fail('動作關鍵點過多。')
    return {'animations': list(animations), 'mouth': any(name.casefold() in ('mouth', 'mouth_open', 'jaw') for name in bone_names)}


def validate_free_skeletal_archive(content):
    zip_bound(content)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 64 or sum(row.file_size for row in entries) > 40 * 1024 * 1024:
                fail('解壓後太大或檔案太多。')
            files, folded = {}, set()
            for row in entries:
                path = row.orig_filename.rstrip('/')
                if not safe_path(path):
                    fail('ZIP 路徑不安全。')
                if row.is_dir():
                    continue
                if (path.casefold() in folded or row.flag_bits & 1 or stat.S_ISLNK(row.external_attr >> 16)
                        or row.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    fail('ZIP 有重複、加密或連結檔案。')
                folded.add(path.casefold())
                if row.file_size > MAX_TEXTURE:
                    fail('ZIP 單一檔案過大。')
                files[path] = row
            if not {'rigby-manifest.json', ENTRYPOINT, 'model.atlas'}.issubset(files):
                fail('需要 rigby-manifest.json、model.rigby.json 及 model.atlas；不接受二進位 Spine。')
            manifest = read_json(archive.read(files['rigby-manifest.json']), 8192)
            if (not isinstance(manifest, dict) or manifest.get('format') != FORMAT
                    or manifest.get('skeleton') != ENTRYPOINT or manifest.get('atlas') != 'model.atlas'):
                fail('請匯入明確標示 rigby-json-zip/v1 的模型。')
            licence = manifest.get('license', {})
            if not isinstance(licence, dict) or not name_ok(licence.get('name')) or not name_ok(licence.get('author')):
                fail('請保留模型作者及授權說明；免費 renderer 不代表模型素材免費。')
            if files[ENTRYPOINT].file_size > MAX_JSON or files['model.atlas'].file_size > MAX_ATLAS:
                fail('骨架或貼圖清單太大。')
            doc = read_json(archive.read(files[ENTRYPOINT]), MAX_JSON)
            atlas = archive.read(files['model.atlas']).decode('utf-8-sig')
            pages, regions = parse_atlas(atlas)
            validate_skeleton(doc, regions)
            required = {'rigby-manifest.json', ENTRYPOINT, 'model.atlas'}
            texture_bytes = 0
            for page in pages:
                path = page['name']
                if path not in files:
                    fail('ZIP 缺少貼圖。')
                required.add(path)
                texture_bytes += files[path].file_size
                with archive.open(files[path]) as stream, Image.open(stream) as image:
                    if image.format != 'PNG' or list(image.size) != page['size']:
                        fail('貼圖不是 PNG 或實際尺寸與清單不符。')
                    image.verify()
            if texture_bytes > 32 * 1024 * 1024:
                fail('貼圖總大小超限。')
            for path, row in files.items():
                if path not in required and (not path.lower().endswith(('.txt', '.md')) or row.file_size > 1024 * 1024):
                    fail('ZIP 含有未使用資源、程式或尚未支援的格式。')
                with archive.open(row) as stream:
                    while stream.read(65536):
                        pass
            return ENTRYPOINT
    except (zipfile.BadZipFile, UnicodeError, OSError, RuntimeError, KeyError, TypeError,
            AttributeError, IndexError, RecursionError, json.JSONDecodeError, Image.DecompressionBombError) as error:
        raise ValueError('免費骨架 ZIP 未能安全核對；原有角色保留。') from error
