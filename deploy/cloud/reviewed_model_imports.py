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

STATIC_MODEL_CREDITS.update({'cloud-live2d-3fb2cbe007a25f2a43fa29ee83e961e4e41a8ce4b70e06453071c3c1981e3a09': {'author': 'xShiroeNguyenx', 'name': 'Gothic Angel', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-e8158b82da47669d0ce099a4d7b573ccc8b87f21550fcef221120504c33a70b4': {'author': 'xShiroeNguyenx', 'name': 'Gothic Aristocrat', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-414f8d042fd34a9bfd8c40f25822c5b8877d1a32012ad41db08e1fdc1b283cae': {'author': 'xShiroeNguyenx', 'name': 'Gothic Kawaii', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-d15644ddeacc66f0eeca5dcb2dd3372fb655547917c1dda6e7ded2c5fa950555': {'author': 'xShiroeNguyenx', 'name': 'Gothic Lolita', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-d1e8e0403ebb016a7a4eb1f29b5b3caa7a4fc8d88f3ba88adbc8c7f740f1daa9': {'author': 'xShiroeNguyenx', 'name': 'Pink Aristocrat', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-35e41aab1895a54e802c62660dc6c28c7ceba1acb8a38c0e7c4318adac187d3d': {'author': 'xShiroeNguyenx', 'name': 'Pink Kawaii', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-eb175cfa6644c6f853cca791fbd71047ea55564618c786be463c8d544ef710dd': {'author': 'xShiroeNguyenx', 'name': 'Pink Pastel', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-e73d87bba2b010100b743ef5bdae00b29a4e6fa083f4898fafd36cdbe11e6259': {'author': 'xShiroeNguyenx', 'name': 'Snow Angel', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-c526645ead0eb807bff95a2b177c5fab1d977d163261c7f74e805965c0339c71': {'author': 'xShiroeNguyenx', 'name': 'Snow Aristocrat', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-ff2c775d7d38eac96270466ed2c216bbeb090fb36f02f2fe2a533b8db2f713e3': {'author': 'xShiroeNguyenx', 'name': 'Snow Dancer', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-be3152911770e8b57b700787c5ac137da5e7f95a5f31744ad023746d300ee36a': {'author': 'xShiroeNguyenx', 'name': 'Snow Pastel', 'notice': 'CC BY-NC 4.0; noncommercial educational use. Original art, motions and full attribution retained. 鄰伴只整理執行封裝、引用路徑及完整取景，原模型／貼圖／動作不變；對話不代表原作者。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}})

# Exact newly reviewed originals and explicitly labelled legal palette derivatives.
STATIC_MODEL_CREDITS.update({'cloud-live2d-fb765cff068fdf9939b6305c91918475721cffbb366b164ea03a45fe41421db9': {'author': 'tsunehimatoi / PSD2Live Examples', 'name': 'TML · 原創示例', 'notice': 'CC0 1.0. AI-generated original example artwork, not a claim of hand drawing. Runtime/model/motion bytes unchanged; packaging and contain framing only. Texture bytes unchanged.', 'source': 'https://github.com/tsunehimatoi/psd2live-examples/tree/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/cases/tml', 'terms': 'https://github.com/tsunehimatoi/psd2live-examples/blob/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/LICENSE'}, 'cloud-live2d-0466e9e92b6b402dbdce663771f1a11cc529b456225d629e137958b2cab85e8a': {'author': 'tsunehimatoi / PSD2Live Examples', 'name': 'DS · 動作示例', 'notice': 'CC0 1.0. AI-generated original example artwork, not a claim of hand drawing. Runtime/model/motion bytes unchanged; packaging and contain framing only. Texture bytes unchanged.', 'source': 'https://github.com/tsunehimatoi/psd2live-examples/tree/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/cases/ds', 'terms': 'https://github.com/tsunehimatoi/psd2live-examples/blob/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/LICENSE'}, 'cloud-live2d-f45b3c4599feab50e8dfd624ac44f55baaa5654cd83dd9f8106b708e017b8c39': {'author': 'tsunehimatoi / PSD2Live Examples', 'name': 'Star Lan · 星瀾', 'notice': 'CC0 1.0. AI-generated original example artwork, not a claim of hand drawing. Runtime/model/motion bytes unchanged; packaging and contain framing only. Star Lan texture atlases downsampled to2048px with Lanczos to fit32million-pixel safety limit; artwork composition retained.', 'source': 'https://github.com/tsunehimatoi/psd2live-examples/tree/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/cases/star_lan', 'terms': 'https://github.com/tsunehimatoi/psd2live-examples/blob/32bc3487d6fbc29f1680d4c70b94e526f6b944a8/LICENSE'}, 'cloud-live2d-8b93e71f792d13de4588c99b7c469e82f3f0e6cc9389257780812b5dafaa5c31': {'author': 'MoFox-Studio', 'name': 'MoFox · 小狐狸', 'notice': 'Noncommercial educational sharing with source credit. Original ZIP unchanged byte for byte; no art/model modification, no commercial use or false authorship.', 'source': 'https://github.com/MoFox-Studio/MoFox-ArtCollection', 'terms': 'https://github.com/MoFox-Studio/MoFox-ArtCollection/blob/e59a4305c0ed8a815c8387bd2d25fee633e72dc3/README.md'}, 'cloud-live2d-48423e06d0e41f62d829a9d17a376f40bd41a6941fe02f737d14213057fcbe17': {'author': 'xShiroeNguyenx', 'name': 'Snow · 冬日外套 · 薄荷配色', 'notice': '配色衍生款；原型：Snow · 冬日外套。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-e4b5b6addbc75ea59f32787f98c3165655d444112c272189ddd98eade20915c1': {'author': 'xShiroeNguyenx', 'name': 'Snow · 冬日外套 · 薰衣草配色', 'notice': '配色衍生款；原型：Snow · 冬日外套。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-400dc40a5d91d7e0b5c81e86aa08f885e5b6726566f5d80651c2bea828bb9aa4': {'author': 'xShiroeNguyenx', 'name': 'Snow · 冬日外套 · 櫻莓配色', 'notice': '配色衍生款；原型：Snow · 冬日外套。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-3509faf5c4906d9fcdbb22d4839088d6e384a8bf1eb5697aa372dca6a4b0a274': {'author': 'xShiroeNguyenx', 'name': 'Gothic Pastel · 夢幻哥德 · 薄荷配色', 'notice': '配色衍生款；原型：Gothic Pastel · 夢幻哥德。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-254ef2fd00442312cb6b300fe0e2baa37ee8174114ad5eeb4a430a655909199d': {'author': 'xShiroeNguyenx', 'name': 'Gothic Pastel · 夢幻哥德 · 薰衣草配色', 'notice': '配色衍生款；原型：Gothic Pastel · 夢幻哥德。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-06ec51a8f43f4dc2e4eaf01bb03996b5651bab3c1a89c5cbebf8d81558ecf07c': {'author': 'xShiroeNguyenx', 'name': 'Gothic Pastel · 夢幻哥德 · 櫻莓配色', 'notice': '配色衍生款；原型：Gothic Pastel · 夢幻哥德。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-e538758d52389f5c2b19fa1191daeacdd8de017eee591321f7517ef4f097e86d': {'author': 'xShiroeNguyenx', 'name': 'Pink Angel · 櫻色天使 · 薄荷配色', 'notice': '配色衍生款；原型：Pink Angel · 櫻色天使。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-749026e265ece998f0d2415dd84e7579733a307ceebbaa35e5ca89f4ae8471b3': {'author': 'xShiroeNguyenx', 'name': 'Pink Angel · 櫻色天使 · 薰衣草配色', 'notice': '配色衍生款；原型：Pink Angel · 櫻色天使。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-1989098a780e2a7dc5e5b71365e85fae22e6700f50444883605ffe0c4f133de8': {'author': 'xShiroeNguyenx', 'name': 'Pink Angel · 櫻色天使 · 櫻莓配色', 'notice': '配色衍生款；原型：Pink Angel · 櫻色天使。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-f813d9dde745fb9bfc1c9c86858639098369946992b0a29ef90ebfe4651a5490': {'author': 'xShiroeNguyenx', 'name': 'Snow Kawaii · 雪色貓咪 · 薄荷配色', 'notice': '配色衍生款；原型：Snow Kawaii · 雪色貓咪。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-74c9d84971b05535d7650d82772fa100fcec03d7c0e4b79f104a5c5d5334f244': {'author': 'xShiroeNguyenx', 'name': 'Snow Kawaii · 雪色貓咪 · 薰衣草配色', 'notice': '配色衍生款；原型：Snow Kawaii · 雪色貓咪。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-4bdafd6ad0f5d53e159e864fdff7368c303d1b2aa3829e719379e0a8a5c9f393': {'author': 'xShiroeNguyenx', 'name': 'Snow Kawaii · 雪色貓咪 · 櫻莓配色', 'notice': '配色衍生款；原型：Snow Kawaii · 雪色貓咪。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4ab4ae6461949aa4f1b6cfb6fcf5a1b8ac42f18c/ASSETS-LICENSE.md'}, 'cloud-live2d-3750d9037d426c8c229269aa6f13716027588a3d57d8dc74f0adc454f3aaa72c': {'author': 'xShiroeNguyenx', 'name': 'Gothic Dream · 哥德夢境 · 薄荷配色', 'notice': '配色衍生款；原型：Gothic Dream · 哥德夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-eca00bc2a361075287a97d1b10652cfe7ef2d16105ddf877c39d00dcc9225e52': {'author': 'xShiroeNguyenx', 'name': 'Gothic Dream · 哥德夢境 · 薰衣草配色', 'notice': '配色衍生款；原型：Gothic Dream · 哥德夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-4fece5977625b40e2ef3a7d94fcd5f3f5c39a2e187a3d4912312a58bca11a441': {'author': 'xShiroeNguyenx', 'name': 'Gothic Dream · 哥德夢境 · 櫻莓配色', 'notice': '配色衍生款；原型：Gothic Dream · 哥德夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-60b2c3136cb76196229eb3b5fa395d4e14d36beac1640f5e61700782b5507139': {'author': 'xShiroeNguyenx', 'name': 'Pink Dream · 櫻色夢境 · 薄荷配色', 'notice': '配色衍生款；原型：Pink Dream · 櫻色夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-ee9f91688055ceeaa6c25d4a89629d9a2f249e1eb499efb65acd1607f4c4c330': {'author': 'xShiroeNguyenx', 'name': 'Pink Dream · 櫻色夢境 · 薰衣草配色', 'notice': '配色衍生款；原型：Pink Dream · 櫻色夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-f897e32ac37ec56489410ec3335071acf98af294b8c02eb09899dc8ab833565e': {'author': 'xShiroeNguyenx', 'name': 'Pink Dream · 櫻色夢境 · 櫻莓配色', 'notice': '配色衍生款；原型：Pink Dream · 櫻色夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-17f3a69f4205420b7a1b03790f7adad4789586a1507b6e547728b0d90999f8b6': {'author': 'xShiroeNguyenx', 'name': 'Snow Dream · 雪色夢境 · 薄荷配色', 'notice': '配色衍生款；原型：Snow Dream · 雪色夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-38daa192bc1ad534f0499f297f6e7e7c0e032621fa84953ed69d744e910c7864': {'author': 'xShiroeNguyenx', 'name': 'Snow Dream · 雪色夢境 · 薰衣草配色', 'notice': '配色衍生款；原型：Snow Dream · 雪色夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-5fc8763f3e012d9770dfc48ab228f3688242a2765752d27caedbb3a81f103146': {'author': 'xShiroeNguyenx', 'name': 'Snow Dream · 雪色夢境 · 櫻莓配色', 'notice': '配色衍生款；原型：Snow Dream · 雪色夢境。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-725bfc7a7ef1775394ba9c4af224b4355fcab78f32e8b72c224e788def60ec55': {'author': 'xShiroeNguyenx', 'name': 'Gothic Angel · 薄荷配色', 'notice': '配色衍生款；原型：Gothic Angel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-7b45b606d9abbbc47c69b364bf9fb98ca768c3119ddbad6272a84f3b3330c77d': {'author': 'xShiroeNguyenx', 'name': 'Gothic Angel · 薰衣草配色', 'notice': '配色衍生款；原型：Gothic Angel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-1ebe0e4ed75f3507a0413cc1e61d8878e09040254fe971d08764b6f531cf02fb': {'author': 'xShiroeNguyenx', 'name': 'Gothic Angel · 櫻莓配色', 'notice': '配色衍生款；原型：Gothic Angel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-7543d9ecc79c9b742c5dfc725d2968802eaf841fc5fa5be36ce9cd2433809ab5': {'author': 'xShiroeNguyenx', 'name': 'Gothic Aristocrat · 薄荷配色', 'notice': '配色衍生款；原型：Gothic Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-178e179165ffc18a0db240a65374f0ec84537ef6580fff7d54dcbaf73ee237c7': {'author': 'xShiroeNguyenx', 'name': 'Gothic Aristocrat · 薰衣草配色', 'notice': '配色衍生款；原型：Gothic Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-9be0a24603da6949d12dead17a10a9a421decf9bd3b4cfccd59c453d4bc0ed26': {'author': 'xShiroeNguyenx', 'name': 'Gothic Aristocrat · 櫻莓配色', 'notice': '配色衍生款；原型：Gothic Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-122d466718031fada40d2f3af2a03827895d310459661d7d8b5417a316f94107': {'author': 'xShiroeNguyenx', 'name': 'Gothic Kawaii · 薄荷配色', 'notice': '配色衍生款；原型：Gothic Kawaii。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-863fe74298def78d4321e34c84dbc178f46ee8df538d34a9303ea6aec6b7d7b6': {'author': 'xShiroeNguyenx', 'name': 'Gothic Kawaii · 薰衣草配色', 'notice': '配色衍生款；原型：Gothic Kawaii。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-2825efb528bd636548b70978f96fc760b3cdc1b749abe4b548763de67563d20a': {'author': 'xShiroeNguyenx', 'name': 'Gothic Kawaii · 櫻莓配色', 'notice': '配色衍生款；原型：Gothic Kawaii。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-1d557fe931fba5e5d27763b074a20f5a55d413ccabeb1636018f0f3c5f8c547a': {'author': 'xShiroeNguyenx', 'name': 'Gothic Lolita · 薄荷配色', 'notice': '配色衍生款；原型：Gothic Lolita。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-d505e09447406fbe4ab8eebc69ec3d0554e977c022f3753690b30d893e2c7527': {'author': 'xShiroeNguyenx', 'name': 'Gothic Lolita · 薰衣草配色', 'notice': '配色衍生款；原型：Gothic Lolita。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-05e68f9bc3312303da6e4e66128daef455eff70687b88fbdfb2eff033402d87b': {'author': 'xShiroeNguyenx', 'name': 'Gothic Lolita · 櫻莓配色', 'notice': '配色衍生款；原型：Gothic Lolita。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-05144b3bce144f61adef3d80e760bb37ac21abeffdc585487ad441e363bc0e2b': {'author': 'xShiroeNguyenx', 'name': 'Pink Aristocrat · 薄荷配色', 'notice': '配色衍生款；原型：Pink Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-abb6a6ffecf1e81034f763fdc3ad824b37f6f5f5d24b7625269c5a0ec5b4f61f': {'author': 'xShiroeNguyenx', 'name': 'Pink Aristocrat · 薰衣草配色', 'notice': '配色衍生款；原型：Pink Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-1a29274355149cb797b24606ba224483d26442ba5f4989324ae4006c6754ac49': {'author': 'xShiroeNguyenx', 'name': 'Pink Aristocrat · 櫻莓配色', 'notice': '配色衍生款；原型：Pink Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-a3f260cb80ea1d6449484815421f8bce3ef0ebea00f675b0891708efeafa99b1': {'author': 'xShiroeNguyenx', 'name': 'Pink Kawaii · 薄荷配色', 'notice': '配色衍生款；原型：Pink Kawaii。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-0869c4dbf13fc15c911876f02760c9c6963c1a8c420aa139e8b5a1d819976b39': {'author': 'xShiroeNguyenx', 'name': 'Pink Kawaii · 薰衣草配色', 'notice': '配色衍生款；原型：Pink Kawaii。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-f67c44352f045350a0e29daee510f645b85d4b4c31d7ee1be352b7300279b6ff': {'author': 'xShiroeNguyenx', 'name': 'Pink Kawaii · 櫻莓配色', 'notice': '配色衍生款；原型：Pink Kawaii。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-50cc9baae31ac9780e84c89ef2374579d51b42233505cf4b3ffc85c1c445a05d': {'author': 'xShiroeNguyenx', 'name': 'Pink Pastel · 薄荷配色', 'notice': '配色衍生款；原型：Pink Pastel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-663f913e56cf38c4d2def3787227366a95f9390317086438d2e1ab6baf890c69': {'author': 'xShiroeNguyenx', 'name': 'Pink Pastel · 薰衣草配色', 'notice': '配色衍生款；原型：Pink Pastel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-662a507731da9b2105907f798391c333deb1848ac01ef2d8faa23c0f06237974': {'author': 'xShiroeNguyenx', 'name': 'Pink Pastel · 櫻莓配色', 'notice': '配色衍生款；原型：Pink Pastel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-6ed6abb739d306f8d5489e7a6d8ce93ac906ee20b08bf0bc37e355de28f5e490': {'author': 'xShiroeNguyenx', 'name': 'Snow Angel · 薄荷配色', 'notice': '配色衍生款；原型：Snow Angel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-ecc62239f5491cb2987d79608fd959996726d149e1d7556fb684f9a8eb6cbd8d': {'author': 'xShiroeNguyenx', 'name': 'Snow Angel · 薰衣草配色', 'notice': '配色衍生款；原型：Snow Angel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-42b52c103f5dcaa53ea79d674a58f85e4bef1fec46fb260ab50753dee748c751': {'author': 'xShiroeNguyenx', 'name': 'Snow Angel · 櫻莓配色', 'notice': '配色衍生款；原型：Snow Angel。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-4d6de16fa0e88ddb5aa531bfca5220948aedf313a8c5a45b88c482d54a90c274': {'author': 'xShiroeNguyenx', 'name': 'Snow Aristocrat · 薄荷配色', 'notice': '配色衍生款；原型：Snow Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薄荷配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-a86f25b3fef55a2212d5d8fcc3dc6615e1cc2723da06e1acc4b541480480fe03': {'author': 'xShiroeNguyenx', 'name': 'Snow Aristocrat · 薰衣草配色', 'notice': '配色衍生款；原型：Snow Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（薰衣草配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}, 'cloud-live2d-a2e655c52d5fd2106f707592d832f09930dbca75ae4bca0de10ecb2d6e766d22': {'author': 'xShiroeNguyenx', 'name': 'Snow Aristocrat · 櫻莓配色', 'notice': '配色衍生款；原型：Snow Aristocrat。原作者 xShiroeNguyenx；FWFT／鄰伴只修改冷色及粉色頭髮、衣服及眼睛貼圖配色（櫻莓配色），保留暖膚色、透明度、線稿及模型動作。依 CC BY-NC 4.0 非商業學習使用；保留原作者、來源及授權，不代表原作者認可，並非新原創角色或新獨立圖庫。', 'source': 'https://github.com/xShiroeNguyenx/desktop-companion/tree/4a9170a13c4fb702e35c68a2311d5fa27088b6d5', 'terms': 'https://github.com/xShiroeNguyenx/desktop-companion/blob/4a9170a13c4fb702e35c68a2311d5fa27088b6d5/ASSETS-LICENSE.md'}})

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
