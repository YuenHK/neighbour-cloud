"""Reuse the existing workbench with an explicit cloud request adapter.

No operator key, native iframe, robot background task, local resource monitor
or provider-settings editor is installed into the cloud page.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / 'edge_hub/static'
SCRIPTS = ('photo-privacy.js', 'latest-photo.js', 'work-sections.js', 'service-workbench.js',
           'api-quota.js', 'estate-management.js', 'workspace-navigation.js')


def cut(source, start, end):
    if source.count(start) != 1 or source.count(end) != 1:
        raise ValueError('cloud_admin_anchor_requires_review')
    before, rest = source.split(start, 1)
    return before + end + rest.split(end, 1)[1]


class CloudAdminAssets:
    def __init__(self, static=STATIC, *, governance=False):
        if type(governance) is not bool:
            raise ValueError('explicit_cloud_governance_assets_mode_required')
        static = Path(static)
        html = (static / 'admin.html').read_text(encoding='utf-8')
        inline = re.findall(r'<script>([\s\S]*?)</script>', html)
        if len(inline) != 1:
            raise ValueError('cloud_admin_inline_requires_review')
        html = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html)
        html = re.sub(r'<a role="tab" id="tab-avatar"[^>]*>[\s\S]*?</a>', '', html)
        html = cut(html, '<section id="panel-avatar"', '<section id="panel-usage"')
        html = cut(html, '<section class="service-card"><h2>服務狀態</h2>',
                   '<section class="service-card" aria-labelledby="quotaHeading">')
        html = cut(html, '<section class="service-card" id="localResourcesCard">', '<footer class="service-footer">')
        # Keep the enclosing usage tab closed after removing its native card.
        html = html.replace('<footer class="service-footer">', '</section><footer class="service-footer">', 1)
        html = html.replace('__SERVICE_SHELL__', '').replace('__LOCAL_OPERATOR_TOKEN__', '')
        html = html.replace('本機可用量', '系統守護可用量').replace('官方餘額與本機保守限制', '官方餘額與系統保守限制')
        html = html.replace('</body>', '<script type="module" src="/cloud/admin-entry.js"></script></body>')
        runtime = "import { cloudFetch as fetch } from '/cloud/admin-request.js'\n" + inline[0]
        runtime = runtime.replace("link.href = '/admin#work'", "link.href = '/cloud/admin#work'")
        self.responses = {'/cloud/admin': (html.encode(), 'text/html'),
            '/cloud/admin/runtime.js': (runtime.encode(), 'text/javascript'),
            '/assets/service-shell.css': ((static / 'service-shell.css').read_bytes(), 'text/css'),
            '/assets/service/service-mark.svg': ((static / 'service-mark.svg').read_bytes(), 'image/svg+xml')}
        for name in SCRIPTS + (('governance.js',) if governance else ()):
            script = (static / name).read_text(encoding='utf-8')
            if name == 'estate-management.js':
                start = '  let resourcesReading = false'
                if script.count(start) != 1:
                    raise ValueError('cloud_admin_resource_anchor_requires_review')
                script = script.split(start, 1)[0] + '})()\n'
                script = script.replace("`quota${refresh ? '?refresh=true' : ''}`", "'quota'")
            if name == 'workspace-navigation.js':
                script = script.replace(', avatar: []', '')
            if name == 'api-quota.js':
                script = script.replace('本機', '系統守護')
            if name == 'governance.js':
                script = script.replace('已檢查資料庫及隔離復原；不包含相片原檔、金鑰、模型或機體控制設定，亦未取代正式資料。',
                    '包括已保存的巡查相片；金鑰、模型及機體控制設定分開保留。復原前須再核對現行清除紀錄及用量，不會自動替換正式資料。')
            self.responses['/cloud/admin/' + name] = (
                ("import { cloudFetch as fetch } from '/cloud/admin-request.js'\n" + script).encode(), 'text/javascript')

    def get(self, path):
        return self.responses.get(path)
