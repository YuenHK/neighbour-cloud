"""Immutable shared Live2D archives in the existing durable estate database.

Schema installation is an explicit stopped-writer operation. Importing this
module or opening an HTTP route never migrates, publishes or deletes a model.
"""
import hashlib
import io
import json
import posixpath
import re
import stat
import threading
import time
import zipfile
from collections import OrderedDict
from contextlib import closing
from urllib.parse import unquote

from PIL import Image

MAX_ARCHIVE = 32 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
CHUNK = 256 * 1024
MODEL_ID = re.compile(r'cloud-live2d-([a-f0-9]{64})$')
TABLES = {'cloud_avatar_models', 'cloud_avatar_model_chunks'}


def model_digest(identity):
    match = MODEL_ID.fullmatch(identity) if isinstance(identity, str) else None
    if match is None:
        raise ValueError('模型編號不正確。')
    return match[1]


def archive_path(value):
    if (not isinstance(value, str) or not value or len(value) > 240 or '\\' in value
            or '\x00' in value or value.startswith('/') or ':' in value or '?' in value or '#' in value
            or '..' in value.split('/')):
        raise ValueError('模型檔案路徑不正確。')
    path = posixpath.normpath(value)
    if path in ('', '.') or path.startswith('../'):
        raise ValueError('模型檔案路徑不正確。')
    return path


def validate_archive(content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_ARCHIVE:
        raise ValueError('Live2D ZIP 最大為 32 MB；原有模型不會被覆蓋。')
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            entries = archive.infolist()
            if not 1 <= len(entries) <= 1024 or sum(row.file_size for row in entries) > 128 * 1024 * 1024:
                raise ValueError('模型解壓後太大或檔案數量太多。')
            files, settings = {}, []
            pixels = 0
            for row in entries:
                name = archive_path(row.filename.rstrip('/'))
                if row.is_dir():
                    continue
                if (name in files or row.flag_bits & 1 or stat.S_ISLNK(row.external_attr >> 16)
                        or row.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise ValueError('模型包含重複、加密或不支援的檔案。')
                files[name] = row
                ignored = '__MACOSX' in name.split('/') or posixpath.basename(name) == '.DS_Store'
                suffix = posixpath.splitext(name)[1].lower()
                if not ignored and suffix not in ('.json', '.moc3', '.cmo3', '.can3', '.png', '.jpg', '.jpeg', '.webp', '.txt', '.md'):
                    raise ValueError('此發佈功能只接納 Live2D 模型、圖片及設定，不接納程式或額外音效。')
                if row.file_size > 64 * 1024 * 1024:
                    raise ValueError('模型內單一檔案太大。')
                # Read every member with a bounded buffer, validating ZIP CRC.
                with archive.open(row) as stream:
                    while stream.read(64 * 1024):
                        pass
                if ignored:
                    continue
                if name.endswith('.model3.json'):
                    if row.file_size > 2 * 1024 * 1024:
                        raise ValueError('模型設定檔太大。')
                    settings.append((name, json.loads(archive.read(row).decode('utf-8-sig'))))
                if suffix in ('.png', '.jpg', '.jpeg', '.webp'):
                    with archive.open(row) as stream, Image.open(stream) as image:
                        if not 0 < image.width <= 8192 or not 0 < image.height <= 8192:
                            raise ValueError('模型圖片尺寸太大。')
                        pixels += image.width * image.height
                        image.verify()
                if suffix == '.moc3':
                    with archive.open(row) as stream:
                        if stream.read(4) != b'MOC3':
                            raise ValueError('Live2D 模型資料未能核對。')
            if len(settings) != 1 or pixels > 32 * 1024 * 1024:
                raise ValueError('請匯入只包含一個 Live2D 3 模型的 ZIP；圖片總尺寸不可超過 32 百萬像素。')
            name, config = settings[0]
            refs = config.get('FileReferences', {})
            if config.get('Version') != 3 or not isinstance(refs, dict):
                raise ValueError('需要 Live2D 3 的 model3.json 設定。')
            required = [refs.get('Moc')]
            textures = refs.get('Textures')
            if not isinstance(textures, list) or not 1 <= len(textures) <= 16:
                raise ValueError('模型缺少圖片設定。')
            required.extend(textures)
            required.extend(refs[key] for key in ('Physics', 'Pose', 'DisplayInfo', 'UserData') if refs.get(key))
            for expression in refs.get('Expressions', []):
                required.append(expression['File'])
            for group in refs.get('Motions', {}).values():
                for motion in group:
                    if motion.get('Sound'):
                        raise ValueError('請使用不含額外音效的模型，保留平台原有曉曼語音。')
                    required.append(motion['File'])
            for reference in required:
                relative = archive_path(unquote(reference))
                resolved = archive_path(posixpath.join(posixpath.dirname(name), relative))
                if resolved not in files:
                    raise ValueError('模型設定引用了 ZIP 以外或不存在的檔案。')
            if not required[0].lower().endswith('.moc3'):
                raise ValueError('模型缺少 moc3 資料。')
            return name
    except (zipfile.BadZipFile, OSError, UnicodeError, TypeError, KeyError, AttributeError, RuntimeError) as error:
        raise ValueError('模型 ZIP 未能核對；原有模型保留。') from error


def install(db):
    if db.in_transaction:
        raise ValueError('avatar_schema_requires_dedicated_stopped_writer_connection')
    with db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS cloud_avatar_models('
                   'digest TEXT PRIMARY KEY,name TEXT NOT NULL,bytes INTEGER NOT NULL,'
                   'parts INTEGER NOT NULL,uploaded_ms INTEGER NOT NULL,entrypoint TEXT NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS cloud_avatar_model_chunks('
                   'digest TEXT NOT NULL,part INTEGER NOT NULL,content BLOB NOT NULL,PRIMARY KEY(digest,part))')
        expected = {'cloud_avatar_models': ['digest', 'name', 'bytes', 'parts', 'uploaded_ms', 'entrypoint'],
                    'cloud_avatar_model_chunks': ['digest', 'part', 'content']}
        for name, fields in expected.items():
            if [row[1] for row in db.execute('PRAGMA table_info(' + name + ')')] != fields:
                raise ValueError('avatar_schema_requires_review')


class AvatarAssets:
    def __init__(self, connect):
        self.connect = connect  # Dedicated connections; no long estate-store lock.
        self.cache = OrderedDict()
        self.cache_lock = threading.Lock()

    def catalog(self):
        with closing(self.connect(True)) as db:
            rows = db.execute('SELECT digest,name,bytes,parts,uploaded_ms,entrypoint FROM cloud_avatar_models '
                              'ORDER BY uploaded_ms DESC,digest LIMIT 101').fetchall()
        if len(rows) > 100:
            raise ValueError('model_inventory_requires_review')
        return [self.metadata(row) for row in rows]

    @staticmethod
    def metadata(row):
        return {'id': 'cloud-live2d-' + row[0], 'sha256': row[0], 'name': row[1], 'bytes': row[2],
                'format': 'live2d-zip', 'uploaded_ms': row[4], 'entrypoint': row[5]}

    def put(self, identity, name, content):
        digest = model_digest(identity)
        if hashlib.sha256(content).hexdigest() != digest:
            raise ValueError('上載內容摘要不一致；沒有發佈。')
        entrypoint = validate_archive(content)
        name = name.strip()
        if not 1 <= len(name) <= 100 or any(ord(char) < 32 for char in name):
            raise ValueError('模型名稱不正確。')
        parts = (len(content) + CHUNK - 1) // CHUNK
        with closing(self.connect(False)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT digest,name,bytes,parts,uploaded_ms,entrypoint FROM cloud_avatar_models WHERE digest=?', (digest,)).fetchone()
            if old:
                if old[2] != len(content) or old[3] != parts:
                    raise ValueError('已保存的模型資料需要核對。')
                return self.metadata(old)
            used, count = db.execute('SELECT COALESCE(SUM(bytes),0),COUNT(*) FROM cloud_avatar_models').fetchone()
            if used + len(content) > MAX_TOTAL or count >= 100:
                raise ValueError('免費模型儲存預留已滿（64 MB）；沒有刪除舊模型或啟用付費。')
            stamped = int(time.time() * 1000)
            for part in range(parts):
                db.execute('INSERT INTO cloud_avatar_model_chunks VALUES(?,?,?)',
                           (digest, part, content[part * CHUNK:(part + 1) * CHUNK]))
            db.execute('INSERT INTO cloud_avatar_models VALUES(?,?,?,?,?,?)',
                       (digest, name, len(content), parts, stamped, entrypoint))
        return self.metadata((digest, name, len(content), parts, stamped, entrypoint))

    def get(self, identity):
        digest = model_digest(identity)
        with self.cache_lock:
            if digest in self.cache:
                self.cache.move_to_end(digest)
                return self.cache[digest]
        with closing(self.connect(True)) as db:
            row = db.execute('SELECT bytes,parts FROM cloud_avatar_models WHERE digest=?', (digest,)).fetchone()
            if row is None:
                return None
            if not 0 < row[0] <= MAX_ARCHIVE or row[1] != (row[0] + CHUNK - 1) // CHUNK:
                raise ValueError('model_inventory_requires_review')
            chunks = []
            for start in range(0, row[1], 4):
                batch = db.execute('SELECT part,content FROM cloud_avatar_model_chunks WHERE digest=? AND part>=? '
                                   'ORDER BY part LIMIT 4', (digest, start)).fetchall()
                if [item[0] for item in batch] != list(range(start, min(start + 4, row[1]))):
                    raise ValueError('model_parts_incomplete')
                chunks.extend(item[1] for item in batch)
            content = b''.join(chunks)
        if len(content) != row[0] or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError('model_digest_mismatch')
        with self.cache_lock:
            self.cache[digest] = content
            while sum(len(value) for value in self.cache.values()) > MAX_TOTAL:
                self.cache.popitem(last=False)
        return content
