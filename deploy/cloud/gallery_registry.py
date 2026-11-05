"""Reviewed source identities, not a list of licensed/ready model binaries.

One provider/catalogue counts once, never once per author, colour or mirror.
Five metadata adapters, existing VRoid OAuth and three pinned runtime sources
have distinct status. A pinned sample does not imply a whole-site catalogue.
"""
import re
from urllib.parse import urlsplit


def source(identity, name, url, domains, formats, mode, note, terms=None, *, one_click_verified=False):
    return {'id': identity, 'name': name, 'url': url, 'domains': domains,
            'formats': formats, 'mode': mode, 'note': note,
            'terms': terms or url, 'one_click_verified': one_click_verified}


SOURCES = (
    source('live2d', 'Live2D 官方', 'https://www.live2d.com/en/learn/sample/', ['live2d.com'],
           ['live2d'], 'metadata', '逐款核對官方及角色個別條款；已驗證款式在可用清單。',
           'https://www.live2d.com/eula/live2d-free-material-license-agreement_en.html'),
    source('vtubernook', 'VTuber Nook', 'https://vtuber-nook.com/category/live2d-3d-pngtuber-models/',
           ['vtuber-nook.com'], ['live2d', 'vrm'], 'metadata', '目錄包含其他格式；免費標記不代表可轉存。'),
    source('aplaybox', '模之屋 Aplaybox', 'https://www.aplaybox.com/model/model', ['aplaybox.com'],
           ['live2d', 'vrm'], 'metadata', '保留作者轉載許可；MMD／PMX 不當作 VRM。'),
    source('vroid', 'VRoid Hub', 'https://hub.vroid.com/en/', ['hub.vroid.com'], ['vrm'],
           'existing_oauth', '沿用已批准的雲端 OAuth；只限已審核及原生試載款式。',
           'https://vroid.pixiv.help/hc/en-us/articles/360011648594-Can-other-users-use-my-characters-without-permission'),
    source('booth', 'BOOTH', 'https://booth.pm/en/search/Live2D?max_price=0', ['booth.pm'],
           ['live2d', 'vrm'], 'metadata', '讀公開免費分類；廣告、PSD、配件及同人模型仍須逐款審核。'),
    source('itch', 'itch.io', 'https://itch.io/game-assets/free/tag-live2d', ['itch.io'],
           ['live2d', 'vrm'], 'metadata', '讀公開免費分類，不讀 checkout／下載驗證頁；分開 runtime 與工程檔。',
           'https://itch.io/docs/legal/terms'),
    source('nizima', 'nizima', 'https://nizima.com/', ['nizima.com'], ['live2d'],
           'requires_provider_integration', '目前公開首頁只有 JavaScript 殼，未核對可用免費目錄 API。'),
    source('steam', 'VTube Studio Workshop', 'https://steamcommunity.com/app/1325860/workshop/',
           ['steamcommunity.com'], ['live2d'], 'requires_account_and_rights',
           '訂閱可用不等於容許原檔轉發；未連 Steam 帳戶或匯入 Workshop 檔。'),
    source('bowlroll', 'BowlRoll', 'https://bowlroll.net/', ['bowlroll.net'], ['live2d', 'vrm'],
           'format_and_rights_review', '多數是 MMD 檔；未核到可轉發 AIRI runtime，不自動轉格式。'),
    source('cgtrader', 'CGTrader', 'https://www.cgtrader.com/free-3d-models/character', ['cgtrader.com'],
           ['vrm'], 'format_and_rights_review', '一般 royalty-free 條款不等於可分享原檔；未核到合資格 VRM。'),
    source('gumroad', 'Gumroad', 'https://gumroad.com/discover?query=live2d&max_price=0', ['gumroad.com'],
           ['live2d', 'vrm'], 'requires_provider_integration', '公開分類尚未有正式連接；不得繞過登入或結帳。'),
    source('kofi', 'Ko-fi', 'https://ko-fi.com/explore', ['ko-fi.com'], ['live2d', 'vrm'],
           'requires_provider_integration', '沒有已核對的公開模型目錄 API；作者個別條款仍適用。'),
    source('viverse', 'VIVERSE', 'https://avatar.viverse.com/avatar', ['avatar.viverse.com'], ['vrm'],
           'requires_account_and_rights', '官方 SDK 可存取已授權用戶頭像；未建立新帳戶或下載私人頭像。',
           'https://docs.viverse.com/developer-tools'),
    source('vrmconsortium', 'VRM Consortium', 'https://vrm.dev/en/', ['vrm.dev'], ['vrm'],
           'reviewed_runtime_import', '一款 pixiv 官方 VRM 1.0 樣本已核原檔授權及 AIRI 眨眼嘴形，可一鍵預覽；不是全站自動目錄。',
           'https://vrm.dev/en/licenses/1.0/', one_click_verified=True),
    source('tsukuyomi', 'つくよみちゃん官方素材', 'https://tyc.rei-yumesaki.net/material/avatar/3d-a/',
           ['tyc.rei-yumesaki.net'], ['vrm'], 'reviewed_runtime_import',
           '完整官方 ZIP 已核摘要；只抽一款短褲版供鄰伴數字人一鍵預覽，保留署名、角色聲明及原條款；不作通用素材轉發。',
           one_click_verified=True),
    source('aituber-onair', 'AITuber OnAir 官方', 'https://miko.aituberonair.com/downloads/',
           ['miko.aituberonair.com'], ['vrm'], 'reviewed_runtime_import',
           '兩款 Miko 已核原檔及 AIRI 試載；作者容許作網站／軟件內容一部分內建，禁止純素材庫分發，不當作全站自動目錄。',
           'https://miko.aituberonair.com/', one_click_verified=True),
    source('ustella', 'U-Stella', 'https://u-stella.co.jp/', ['u-stella.co.jp'], ['vrm'],
           'requires_provider_integration', '原下載入口不可用；未核對新檔案與 VN3 授權。'),
    source('atleone', 'AtleOne', 'https://atleone.com/tubasaneco.html', ['atleone.com'], ['live2d'],
           'rights_review', '可免費使用不等於可轉發模型原檔，未新增共享款式。'),
    source('streamskins', 'Stream Skins', 'https://streamskins.net/free-vtuber-model/', ['streamskins.net'],
           ['live2d'], 'redistribution_prohibited', '官方條款禁止重新上載原檔；免費 Becca 不加入平台共享，會員免費項目亦不當作全免費。',
           'https://streamskins.net/license/'),
    source('live3d', 'Live3D', 'https://live3d.io/', ['live3d.io'], ['vrm'],
           'requires_provider_integration', '未核到可下載及轉存的正式公開目錄；不把預覽當 runtime。'),
    source('litaart', 'Lita Art', 'https://lita-art.net/model/', ['lita-art.net'], ['live2d'],
           'redistribution_prohibited', '官方條款禁止 moc3／PSD 等原檔再分發，沒有加入共享模型。',
           'https://lita-art.net/terms-and-condition/'),
)
REGISTRY = {row['id']: row for row in SOURCES}
SEARCH_DOMAINS = {row['id']: row['domains'] for row in SOURCES}


def valid_source_link(value, source_id=None):
    if not isinstance(value, str) or len(value) > 1600 or any(ord(char) < 32 for char in value):
        return False
    try:
        url = urlsplit(value)
        if url.scheme != 'https' or url.username or url.password or url.port not in (None, 443):
            return False
        host = (url.hostname or '').lower()
        domains = SEARCH_DOMAINS.get(source_id, []) if source_id else [d for ds in SEARCH_DOMAINS.values() for d in ds]
        return any(host == domain or host.endswith('.' + domain) for domain in domains)
    except ValueError:
        return False


def source_id(value):
    return next((row['id'] for row in SOURCES if valid_source_link(value, row['id'])), None)


def registry_snapshot():
    return {'items': [dict(row) for row in SOURCES], 'target_sources': 20,
            'registered_sources': len(SOURCES), 'metadata_adapters': 5,
            'existing_oauth_sources': 1, 'target_complete': False,
            'reviewed_runtime_sources': 3, 'reviewed_runtime_models': 5,
            'reviewed_original_github_models': 2,
            'all_sources_one_click': False,
            'counting_rule': 'Connected catalogues only; creators, mirrors and links do not count as connected platforms.'}


def safe_title(value):
    return re.sub(r'\s+', ' ', str(value)).strip()[:180]
