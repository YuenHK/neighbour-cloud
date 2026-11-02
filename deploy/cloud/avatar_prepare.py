"""Repack an owned runtime ZIP without changing meshes, textures or design.

Pure preparation only: no downloads, database writes, publication or SDK
conversion. The original user file stays in their browser. A real preview and
the existing explicit platform save remain required.
"""
import io
import json
import posixpath
import stat
import struct
import zipfile
from urllib.parse import unquote

from deploy.cloud.avatar_assets import MAX_ARCHIVE, validate_archive


def zip_bound(content):
    # Bound the central directory before ZipFile allocates a ZipInfo per entry.
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_ARCHIVE:
        raise ValueError('請使用不大於 32 MB 的 ZIP；原檔不會被更改。')
    end = content.rfind(b'PK\x05\x06', max(0, len(content) - 65557))
    if end < 0 or end + 22 > len(content):
        raise ValueError('未找到完整 ZIP；RAR、7z、PSD 及編輯器專案不能直接轉為執行模型。')
    _, disk, start_disk, count_disk, count, size, offset, comment = struct.unpack_from('<4s4H2IH', content, end)
    if (disk or start_disk or count_disk != count or not 1 <= count <= 1024
            or size > 1024 * 1024 or offset + size != end or end + 22 + comment != len(content)):
        raise ValueError('ZIP 目錄過大、分卷或格式不受支援。')


def clean_path(name):
    name = name.replace('\\', '/')
    if (not name or len(name) > 240 or '\x00' in name or name.startswith('/')
            or ':' in name or '?' in name or '#' in name or '..' in name.split('/')):
        raise ValueError('ZIP 包含不安全路徑。')
    name = posixpath.normpath(name)
    if name in ('', '.'):
        raise ValueError('ZIP 包含不正確路徑。')
    return name


def prepare_archive(content, entrypoint=None):
    zip_bound(content)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as source:
            files, folded, models = {}, {}, []
            entries = source.infolist()
            if sum(row.file_size for row in entries) > 128 * 1024 * 1024:
                raise ValueError('解壓後超過 128 MB，請先在原作者工具匯出執行版本。')
            for row in entries:
                if row.is_dir():
                    continue
                name = clean_path(row.filename)
                if (row.flag_bits & 1 or stat.S_ISLNK(row.external_attr >> 16)
                        or row.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                        or row.file_size > 64 * 1024 * 1024):
                    raise ValueError('不處理加密、連結或過大的模型檔。')
                key = name.casefold()
                if key in folded:
                    raise ValueError('ZIP 有大小寫重複檔案，不能安全地自動選擇。')
                files[name], folded[key] = row, name
                if name.lower().endswith('.model3.json'):
                    models.append(name)
            models.sort()
            if not models:
                raise ValueError('欠缺 model3.json／moc3 執行模型；不能把 PSD、cmo3 或 Cubism 2 自動轉成 Cubism 3。')
            if entrypoint is None and len(models) > 1:
                return {'models': models}
            selected = entrypoint or models[0]
            if selected not in models:
                raise ValueError('請從 ZIP 中選擇一個實際模型。')
            row = files[selected]
            if row.file_size > 2 * 1024 * 1024:
                raise ValueError('模型設定檔太大。')
            config = json.loads(source.read(row).decode('utf-8-sig'))
            refs = config.get('FileReferences')
            if config.get('Version') != 3 or not isinstance(refs, dict):
                raise ValueError('需要 Live2D 3 執行設定。')
            directory = posixpath.dirname(selected)
            output, mapped = {}, {}
            repairs = ['整理執行檔及移除編輯器／音效檔', '自動完整取景，保留原比例']

            def resource(value):
                if not isinstance(value, str) or not value or len(value) > 240:
                    raise ValueError('模型引用不正確。')
                value = unquote(value).replace('\\', '/')
                if value.startswith('/') or any(char in value for char in (':', '?', '#', '\x00')):
                    raise ValueError('不讀取 ZIP 以外或網上檔案。')
                resolved = posixpath.normpath(posixpath.join(directory, value))
                if resolved.startswith('../') or resolved in ('', '.', '..'):
                    raise ValueError('模型引用超出 ZIP。')
                actual = folded.get(resolved.casefold())
                if actual is None:
                    raise ValueError('模型引用了不存在的檔案，不能憑空修復。')
                if actual not in mapped:
                    suffix = posixpath.splitext(actual)[1].lower()
                    if suffix not in ('.json', '.moc3', '.png', '.jpg', '.jpeg', '.webp'):
                        raise ValueError('模型執行檔格式不受支援。')
                    target = f'resources/{len(mapped):03d}{suffix}'
                    mapped[actual] = target
                    output[target] = source.read(files[actual])
                return mapped[actual]

            refs['Moc'] = resource(refs.get('Moc'))
            textures = refs.get('Textures')
            if not isinstance(textures, list) or not 1 <= len(textures) <= 16:
                raise ValueError('模型欠缺圖片設定。')
            refs['Textures'] = [resource(value) for value in textures]
            for key in ('Physics', 'Pose', 'DisplayInfo', 'UserData'):
                if refs.get(key):
                    refs[key] = resource(refs[key])
            if isinstance(refs.get('MotionSync'), str):
                refs['MotionSync'] = resource(refs['MotionSync'])
            for expression in refs.get('Expressions', []):
                expression['File'] = resource(expression['File'])
            for group in refs.get('Motions', {}).values():
                for motion in group:
                    motion['File'] = resource(motion['File'])
                    motion.pop('Sound', None)
            # Keep attribution and source terms, including nested readme files.
            for name, member in files.items():
                if name.lower().endswith(('.txt', '.md')) and member.file_size <= 1024 * 1024:
                    output[f'notices/{len(output):03d}-' + posixpath.basename(name)] = source.read(member)
            neighbour = config.get('Neighbour', {})
            config['Neighbour'] = {**(neighbour if isinstance(neighbour, dict) else {}), 'fit': 'visible-contain-v1'}
            output['model.model3.json'] = json.dumps(config, ensure_ascii=False).encode('utf-8')
            output['notices/NEIGHBOUR-PREPARATION.txt'] = (
                b'Technical ZIP preparation only. Original meshes and texture bytes unchanged. '
                b'Original creator rights and terms continue to apply. '
                b'Preview before publishing; SDK version conversion is not performed.')
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as target:
                for name, data in output.items():
                    target.writestr(zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0)), data,
                                    compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
            result = buffer.getvalue()
            validate_archive(result)
            return {'content': result, 'entrypoint': selected, 'repairs': repairs,
                    'original_bytes': len(content), 'prepared_bytes': len(result)}
    except (zipfile.BadZipFile, RuntimeError, UnicodeError, OSError, KeyError, TypeError, AttributeError) as error:
        raise ValueError('ZIP 未能安全整理；原檔與平台原有角色保留。') from error
