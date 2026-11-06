"""Download immutable reviewed application assets, never arbitrary user URLs.

The descriptors include author-specific permission to bundle a character inside
Neighbour. This is not a general model file redistribution or mirroring service.
The caller must require a staff session, preserve notices, and preview only until
the existing explicit Save action publishes through the normal 32/64 MiB store.
No database, credentials, cookie jar, OAuth, or model selection is changed here.
"""
import hashlib
import json
import stat
import tempfile
import threading
import time
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import httpx

from .avatar_vrm import MAX_BYTES, validate_vrm

MAX_ARCHIVE_BYTES = 192 * 1024 * 1024
MANIFEST = Path(__file__).with_name('reviewed_model_imports.json')
_HOSTS = {'tyc.rei-yumesaki.net', 'miko.aituberonair.com', 'raw.githubusercontent.com', 'github.com'}

# Static reviewed Live2D files use the normal gallery rather than this VRM-only
# downloader. Resolve their notice by immutable content ID after shared Save as
# well, so another device does not lose the original creator's attribution.
STATIC_MODEL_CREDITS = {
    'cloud-live2d-bc35f1bdbf503abace04cadb524eddbdee5945f717ba265b71505aabde71792f': {
        'name': 'Cat1 · 橙色貓咪',
        'author': 'Boris González / DenpaBorisu',
        'source': 'https://github.com/DenpaBorisu/Live2D_Android_Demo/tree/395bcd5b907fd5f1da68992d63f2666a1bea94ca/AndroidSample/Live2dModels/Cat1',
        'terms': 'https://github.com/DenpaBorisu/Live2D_Android_Demo/blob/395bcd5b907fd5f1da68992d63f2666a1bea94ca/README.md',
        'notice': '作者明確將自己製作的貓咪圖像置於公有領域；模型及貼圖原檔保留。鄰伴僅整理執行封裝及引用路徑，並加入自動構圖標記。沒有複製 Unity 或 Live2D SDK 程式。',
    },
}


STATIC_MODEL_CREDITS.update({'cloud-live2d-0332885fb6f39558557576b87a0da7bd2487f288d657d6202895c1745635dfed': {'author': 'Fili '
                                                                                             '— '
                                                                                             'MjGjVtube '
                                                                                             '/ '
                                                                                             'Gawang '
                                                                                             'Pinoy. '
                                                                                             'Source '
                                                                                             'package '
                                                                                             'CC0 '
                                                                                             '1.0; '
                                                                                             'used '
                                                                                             'for '
                                                                                             'noncommercial '
                                                                                             'education.',
                                                                                   'name': 'Fili',
                                                                                   'notice': '只作本平台非商業學習用途，保留原作者及素材授權；對話不代表作者。Original '
                                                                                             'root '
                                                                                             'LICENSE '
                                                                                             'renamed '
                                                                                             'LICENSE.txt '
                                                                                             'with '
                                                                                             'byte-identical '
                                                                                             'full '
                                                                                             'text '
                                                                                             'solely '
                                                                                             'for '
                                                                                             'safe '
                                                                                             'notice '
                                                                                             'retention. '
                                                                                             'Existing '
                                                                                             'path/framing '
                                                                                             'preparation. '
                                                                                             'MOC3 '
                                                                                             'and '
                                                                                             'PNG '
                                                                                             'unchanged.',
                                                                                   'source': 'https://github.com/MjGjVtube/free-filipino-vtuber-template',
                                                                                   'terms': 'https://github.com/MjGjVtube/free-filipino-vtuber-template/blob/e1c70b0c0ccaaf4274bc537384e9341f80046775/LICENSE'},
 'cloud-live2d-04870a7a2e2b0c85c5d3df9e1cccf3785c22187322b144099649df3bc8bac1f5': {'author': 'Pink '
                                                                                             'Sakura '
                                                                                             '— '
                                                                                             'Ariakage '
                                                                                             '/ '
                                                                                             'live2d-agent-kit, '
                                                                                             'CC '
                                                                                             'BY '
                                                                                             '4.0. '
                                                                                             'AI-assisted '
                                                                                             'original '
                                                                                             'art '
                                                                                             'and '
                                                                                             'rig '
                                                                                             'as '
                                                                                             'detailed '
                                                                                             'in '
                                                                                             'ATTRIBUTION.md. '
                                                                                             'Neighbour '
                                                                                             'technical '
                                                                                             'atlas '
                                                                                             'downsample8192→4096; '
                                                                                             'geometry '
                                                                                             'unchanged.',
                                                                                   'name': 'Pink '
                                                                                           'Sakura',
                                                                                   'notice': '只作本平台非商業學習用途，保留原作者及素材授權；對話不代表作者。Parent '
                                                                                             'explicitly '
                                                                                             'approved '
                                                                                             'deterministic '
                                                                                             'Pillow '
                                                                                             'LANCZOS '
                                                                                             'RGBA '
                                                                                             'atlas '
                                                                                             'downsample8192→4096. '
                                                                                             'All '
                                                                                             'original '
                                                                                             'URLs/SHA '
                                                                                             'and '
                                                                                             'output '
                                                                                             'SHA '
                                                                                             'plus '
                                                                                             'recipe/Pillow '
                                                                                             'version '
                                                                                             'retained. '
                                                                                             'No '
                                                                                             'AI '
                                                                                             'transformation. '
                                                                                             'MOC3 '
                                                                                             'geometry '
                                                                                             'unchanged; '
                                                                                             'original '
                                                                                             'asset '
                                                                                             'license '
                                                                                             'and '
                                                                                             'attribution '
                                                                                             'plus '
                                                                                             'technical-changes '
                                                                                             'notice '
                                                                                             'retained.',
                                                                                   'source': 'https://github.com/Ariakage/live2d-agent-kit',
                                                                                   'terms': 'https://github.com/Ariakage/live2d-agent-kit/blob/354d95800b7d498246dfb658e0e2ee379c29caa4/examples/pink-sakura/LICENSE.md'},
 'cloud-live2d-e43e9d8ac2fdc3e7860ed6dd33f7b8b7177373909b5178ead8593d382711e82d': {'author': 'Nadeshiko '
                                                                                             '— '
                                                                                             'yamato3010, '
                                                                                             'CC '
                                                                                             'BY-NC-SA '
                                                                                             '4.0. '
                                                                                             'NovelAI-assisted '
                                                                                             'original '
                                                                                             'artwork. '
                                                                                             'Noncommercial; '
                                                                                             'retain '
                                                                                             'attribution, '
                                                                                             'license, '
                                                                                             'and '
                                                                                             'share-alike '
                                                                                             'for '
                                                                                             'modifications.',
                                                                                   'name': 'Nadeshiko',
                                                                                   'notice': '只作本平台非商業學習用途，保留原作者及素材授權；對話不代表作者。Existing '
                                                                                             'safe '
                                                                                             'path/framing '
                                                                                             'wrapper. '
                                                                                             'Original '
                                                                                             'README '
                                                                                             'license '
                                                                                             'and '
                                                                                             'custom '
                                                                                             'source-license '
                                                                                             'attribution '
                                                                                             'retained. '
                                                                                             'Original '
                                                                                             'MOC3/PNG '
                                                                                             'unchanged; '
                                                                                             'editor '
                                                                                             'CMO3 '
                                                                                             'not '
                                                                                             'packaged.',
                                                                                   'source': 'https://github.com/yamato3010/live2d-nadeshiko',
                                                                                   'terms': 'https://github.com/yamato3010/live2d-nadeshiko/blob/0a27301bf249c230cd24c697e2fb1f8a3ae59a9b/README.md'}})


STATIC_MODEL_CREDITS.update({'cloud-live2d-9f1ae1e4860d6c3eaeeaf4f48198f38996ceb65dcb775a9b4d6daafb79f9db86': {'author': 'xShiroeNguyenx',
                                                                                   'name': 'Snow '
                                                                                           'Lolita',
                                                                                   'notice': '原作者准許依 '
                                                                                             'CC '
                                                                                             'BY-NC '
                                                                                             '4.0 '
                                                                                             '免費非商用分享及改作，須保留作者、來源及授權連結並標示修改。鄰伴只整理 '
                                                                                             'ZIP '
                                                                                             '路徑、完整取景設定及加入原作者條款／來源說明；moc3、貼圖、動作及表情原檔不變。不得作收費或商業推廣用途；鄰伴對話不代表原作者。',
                                                                                   'source': 'https://github.com/xShiroeNguyenx/desktop-companion',
                                                                                   'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}})


STATIC_MODEL_CREDITS.update({'cloud-live2d-448b5fad226dfc8ce244ac44d0fb4bc295d890180b842e24720082a49b025fc3': {'author': 'xShiroeNguyenx', 'name': 'Gothic Pastel · 夢幻哥德', 'notice': '原作者 xShiroeNguyenx 准許依 CC BY-NC 4.0 免費非商用分享；須保留作者、來源、授權及修改說明。鄰伴只整理 ZIP 路徑、完整取景及加入條款；原模型／貼圖／動作不變，對話不代表作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-f61a267a58d40975391b361026fe436e7521bb8b12c184352f477140167103f3': {'author': 'xShiroeNguyenx', 'name': 'Pink Angel · 櫻色天使', 'notice': '原作者 xShiroeNguyenx 准許依 CC BY-NC 4.0 免費非商用分享；須保留作者、來源、授權及修改說明。鄰伴只整理 ZIP 路徑、完整取景及加入條款；原模型／貼圖／動作不變，對話不代表作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-db08e256d076e9004661f021a01ef042f4a647278a739bf7ee4b74116725404c': {'author': 'xShiroeNguyenx', 'name': 'Snow Kawaii · 雪色貓咪', 'notice': '原作者 xShiroeNguyenx 准許依 CC BY-NC 4.0 免費非商用分享；須保留作者、來源、授權及修改說明。鄰伴只整理 ZIP 路徑、完整取景及加入條款；原模型／貼圖／動作不變，對話不代表作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-3e199a79f3122c227a8da457f3fa93159a0fd2766938a33eba279bc855f03100': {'author': 'jupiterbjy / Cyannyan6', 'name': 'Cyannyan SD · 藍色小夥伴', 'notice': '模型製作 jupiterbjy；原角色 Cyannyan6（同人作品）。依 CC BY-SA 4.0 分享；保留雙方署名、來源、授權及修改說明。鄰伴只整理 ZIP 路徑、完整取景及加入條款；原模型／貼圖／動作不變，對話不代表作者。', 'source': 'https://github.com/jupiterbjy/Live2DPractice-Cyannyan', 'terms': 'https://github.com/jupiterbjy/Live2DPractice-Cyannyan/blob/898d849e594712cd6afb3bb81c07ecc58c59e024/LICENSE.md'}})

STATIC_MODEL_CREDITS.update({'cloud-live2d-ea912942e88f9357d18e34787779a837ef6caa2687d931dc92688fa3db492719': {'author': 'xShiroeNguyenx', 'name': 'Gothic Dream · 哥德夢境', 'notice': 'CC BY-NC 4.0. Noncommercial educational use, retain attribution, source, license and changes notice. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-20bc4a411631ff9935c443d1a2247811284263739836cabf5834a9c36abfc3cf': {'author': 'xShiroeNguyenx', 'name': 'Pink Dream · 櫻色夢境', 'notice': 'CC BY-NC 4.0. Noncommercial educational use, retain attribution, source, license and changes notice. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-aad3c3381402871f723202cdab20b031aa017dd39e223a30ecf5848e4bde02ec': {'author': 'xShiroeNguyenx', 'name': 'Snow Dream · 雪色夢境', 'notice': 'CC BY-NC 4.0. Noncommercial educational use, retain attribution, source, license and changes notice. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-c34c0a74585bb85c0cd8a4be267bcd98b4dbf95dbf9c024cf806dd9d9bf04680': {'author': 'NOM Network and contributors', 'name': 'Melba Toast · 甜心吐司', 'notice': 'Melba Toast (c) 2023-present NOM Network and contributors. Artwork CC BY-SA 4.0; adaptations share alike. Only artwork, no AGPL application code or SDK included. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/NOM-Network/Melba-Toaster', 'terms': 'https://github.com/NOM-Network/Melba-Toaster/blob/5760b98f4a601f26b0b00e7ee8b6edab02c1db63/LICENSE-ASSETS.md'}, 'cloud-live2d-f534c6736ac39e547872941d531bef968093a394edc110857ee739bcd2b076be': {'author': '上善無形 / ZipZipPipe / 氵六青; A8Chann resource packaging', 'name': '鯨魚娘 · 溟月', 'notice': 'CC BY-NC-SA 4.0. Character by 上善无形, derivative design by ZipZipPipe, Live2D rig/motions by 氵六青. Noncommercial, attribution and share alike. Packaging/framing changes only; original artwork retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/A8Chann/dsh-pet-live2d', 'terms': 'https://github.com/A8Chann/dsh-pet-live2d/blob/9b7cd8ed0d16bd23fb098bc0c4fdbac63d89de75/NOTICE.md'}})

class ReviewedImportUnavailable(ValueError):
    """Small public error codes; upstream pages and paths are never echoed."""


@dataclass(frozen=True)
class ReviewedModel:
    id: str
    name: str
    source: str
    source_name: str
    source_url: str
    license_url: str
    credit: str
    notice: str
    bytes: int
    sha256: str
    download_url: str
    download_bytes: int
    download_sha256: str
    member: str | None = None
    application_only: bool = False
    prepare_recipe: str | None = None

    def public(self):
        return {key: getattr(self, key) for key in (
            'id', 'name', 'source', 'source_name', 'source_url', 'license_url',
            'credit', 'notice', 'bytes', 'sha256', 'application_only', 'prepare_recipe')} | {'format': 'vrm'}


def reviewed_models():
    document = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if document.get('version') != 1:
        raise ReviewedImportUnavailable('reviewed_manifest_invalid')
    models = tuple(ReviewedModel(**row) for row in document['models'])
    if len({row.id for row in models}) != len(models):
        raise ReviewedImportUnavailable('reviewed_manifest_invalid')
    for row in models:
        url = urlsplit(row.download_url)
        prepared = row.prepare_recipe == 'vrm-png1024-pillow11.3.0-v1'
        if (url.scheme != 'https' or url.hostname not in _HOSTS or url.port is not None
                or url.username or url.password or url.query or url.fragment
                or not 28 <= row.bytes <= MAX_BYTES
                or not row.bytes <= row.download_bytes <= MAX_ARCHIVE_BYTES
                or len(row.sha256) != 64 or len(row.download_sha256) != 64
                or any(c not in '0123456789abcdef' for c in row.sha256 + row.download_sha256)
                or row.prepare_recipe not in (None, 'vrm-png1024-pillow11.3.0-v1')
                or (prepared and (row.member is not None or row.download_bytes > 64*1024*1024))
                or (url.hostname == 'github.com' and not release_download(row.download_url))
                or (row.member is None and not prepared and (row.bytes != row.download_bytes
                                            or row.sha256 != row.download_sha256))):
            raise ReviewedImportUnavailable('reviewed_manifest_invalid')
    return models


def release_download(value):
    """Only fixed public GitHub release-asset paths may use its CDN redirect."""
    url = urlsplit(value)
    parts = url.path.strip('/').split('/')
    return (url.scheme == 'https' and url.hostname == 'github.com' and len(parts) == 6
            and parts[2:4] == ['releases', 'download'] and all(parts)
            and not url.query and not url.fragment and not url.username and not url.password and not url.port)


@contextmanager
def download_response(client, row):
    headers = {'Accept-Encoding': 'identity'}
    with client.stream('GET', row.download_url, headers=headers) as response:
        if response.status_code in (302, 303, 307) and release_download(row.download_url):
            target = response.headers.get('location', '')
            try:
                url = urlsplit(target)
                safe = (url.scheme == 'https' and url.hostname == 'release-assets.githubusercontent.com'
                    and not url.username and not url.password and url.port is None and not url.fragment
                    and url.path.startswith('/github-production-release-asset-') and len(target) <= 8192)
            except ValueError:
                safe = False
            if not safe:
                raise ReviewedImportUnavailable('model_download_unavailable')
            # Public signed CDN URL stays in memory only. Do not forward even
            # the upstream's cookies; residents' credentials never enter here.
            client.cookies.clear()
            with client.stream('GET', target, headers=headers) as asset:
                yield asset  # No second redirect, automatic retry or URL echo.
        else:
            yield response


class ReviewedModelImporter:
    """One bounded public download at a time, with no implicit retry or publish."""

    def __init__(self, *, transport=None, reviewed=None, deadline_seconds=90):
        self._models = {row.id: row for row in (reviewed_models() if reviewed is None else reviewed)}
        self._transport = transport
        self._gate = threading.BoundedSemaphore(1)
        self._deadline_seconds = deadline_seconds

    def catalogue(self):
        return [row.public() for row in self._models.values()]

    def descriptor(self, identity):
        if not isinstance(identity, str) or identity not in self._models:
            raise ReviewedImportUnavailable('model_not_reviewed')
        return self._models[identity]

    def credit(self, model_id):
        if not isinstance(model_id, str):
            return None
        if model_id in STATIC_MODEL_CREDITS:
            return dict(STATIC_MODEL_CREDITS[model_id])
        if not model_id.startswith('cloud-vrm-'):
            return None
        digest = model_id.removeprefix('cloud-vrm-')
        row = next((row for row in self._models.values() if row.sha256 == digest), None)
        return {'name': row.name, 'author': row.credit, 'source': row.source_url,
                'terms': row.license_url, 'notice': row.notice} if row else None

    def preview(self, identity):
        """Return a pinned validated model, optionally by its reviewed image recipe."""
        row = self.descriptor(identity)
        if not self._gate.acquire(blocking=False):
            raise ReviewedImportUnavailable('model_import_busy')
        try:
            end = time.monotonic() + self._deadline_seconds
            # Disk-backed, private, temporary and deleted even after validation
            # errors. The 176 MB official package is never collected in RAM.
            with tempfile.TemporaryFile() as package:
                with (
                    httpx.Client(transport=self._transport, follow_redirects=False,
                                 trust_env=False, timeout=httpx.Timeout(30, connect=15)) as client,
                    download_response(client, row) as response,
                ):
                    if response.status_code != 200:
                        raise ReviewedImportUnavailable('model_download_unavailable')
                    if response.headers.get('content-encoding', 'identity') != 'identity':
                        raise ReviewedImportUnavailable('model_changed_requires_review')
                    length = response.headers.get('content-length')
                    if length is not None and length != str(row.download_bytes):
                        raise ReviewedImportUnavailable('model_changed_requires_review')
                    digest, size = hashlib.sha256(), 0
                    for part in response.iter_bytes(64 * 1024):
                        if time.monotonic() > end:
                            raise ReviewedImportUnavailable('model_download_timeout')
                        size += len(part)
                        if size > row.download_bytes or size > MAX_ARCHIVE_BYTES:
                            raise ReviewedImportUnavailable('model_changed_requires_review')
                        digest.update(part)
                        package.write(part)
                    if size != row.download_bytes or digest.hexdigest() != row.download_sha256:
                        raise ReviewedImportUnavailable('model_changed_requires_review')
                package.seek(0)
                if row.prepare_recipe:
                    from .reviewed_vrm_prepare import MAX_INPUT, prepare_vrm
                    try:
                        content = prepare_vrm(package.read(MAX_INPUT+1), recipe=row.prepare_recipe,
                            expected_output_sha256=row.sha256)
                    except ValueError as error:
                        raise ReviewedImportUnavailable('model_validation_failed') from error
                else:
                    content = self._extract(package, row) if row.member is not None else package.read(MAX_BYTES + 1)
                if len(content) != row.bytes or hashlib.sha256(content).hexdigest() != row.sha256:
                    raise ReviewedImportUnavailable('model_changed_requires_review')
                try:
                    validate_vrm(content)
                except ValueError as error:
                    raise ReviewedImportUnavailable('model_validation_failed') from error
                return content
        except httpx.HTTPError as error:
            raise ReviewedImportUnavailable('model_download_unavailable') from error
        finally:
            self._gate.release()

    @staticmethod
    def _extract(package, row):
        try:
            with zipfile.ZipFile(package) as archive:
                entries = archive.infolist()
                selected = [entry for entry in entries if entry.filename == row.member]
                if len(entries) > 512 or len(selected) != 1:
                    raise ReviewedImportUnavailable('model_archive_invalid')
                entry = selected[0]
                path = PurePosixPath(entry.filename)
                if (path.is_absolute() or '..' in path.parts or '\\' in entry.filename
                        or ':' in entry.filename or '\x00' in entry.filename
                        or entry.flag_bits & 1 or entry.is_dir()
                        or stat.S_ISLNK(entry.external_attr >> 16)
                        or entry.file_size != row.bytes or entry.file_size > MAX_BYTES):
                    raise ReviewedImportUnavailable('model_archive_invalid')
                # Read only the pinned entry, never extractall or execute files.
                with archive.open(entry) as handle:
                    return handle.read(MAX_BYTES + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as error:
            raise ReviewedImportUnavailable('model_archive_invalid') from error
