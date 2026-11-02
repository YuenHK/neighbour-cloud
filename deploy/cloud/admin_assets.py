"""Reuse the existing workbench with an explicit cloud request adapter.

No operator key, native iframe, robot background task, local resource monitor
or provider-settings editor is installed into the cloud page.
"""
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / 'edge_hub/static'
WEB = Path(__file__).with_name('web')
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
        html = cut(html, '<section id="panel-avatar"', '<section id="panel-usage"')
        html = html.replace('<section id="panel-usage"', (WEB / 'presentation.html').read_text(encoding='utf-8') + '<section id="panel-usage"', 1)
        html = cut(html, '<section class="service-card"><h2>服務狀態</h2>',
                   '<section class="service-card" aria-labelledby="quotaHeading">')
        html = cut(html, '<section class="service-card" id="localResourcesCard">', '<footer class="service-footer">')
        # Keep the enclosing usage tab closed after removing its native card.
        html = html.replace('<footer class="service-footer">', '</section><footer class="service-footer">', 1)
        html = html.replace('__SERVICE_SHELL__', '').replace('__LOCAL_OPERATOR_TOKEN__', '')
        html = html.replace('本機可用量', '系統守護可用量').replace('官方餘額與本機保守限制', '官方餘額與系統保守限制')
        html = html.replace('<th scope="col">官方免費額度</th><th scope="col">系統守護可用量</th>', '<th scope="col">免費配額與可用量</th>')
        html = html.replace('只列目前居民服務使用的平台；進度條表示剩餘比例，官方餘額與系統保守限制分開顯示。', '只列目前使用的服務；進度條表示可用比例。')
        html = html.replace('<p id="quotaFunctions"', '<p hidden id="quotaFunctions"').replace('<p id="quotaLocalStatus"', '<p hidden id="quotaLocalStatus"')
        html = html.replace('</body>', '<script type="module" src="/cloud/admin-entry.js"></script></body>')
        tab = '<a id="tab-robots" href="#robots" role="tab" aria-controls="panel-robots" aria-selected="false" tabindex="-1">機械人控制</a>'
        anchor = '<a role="tab" id="tab-avatar"'
        if html.count(anchor) != 1:
            raise ValueError('cloud_robot_navigation_anchor_requires_review')
        html = html.replace(anchor, tab + anchor, 1)
        html = html.replace('<section id="panel-avatar"', (WEB / 'robots.html').read_text(encoding='utf-8') + '<section id="panel-avatar"', 1)
        runtime = "import { cloudFetch as fetch } from '/cloud/admin-request.js'\n" + inline[0]
        runtime = runtime.replace('timeoutMs = 3000', 'timeoutMs = 12000')
        start = '        const [events, stats] = await Promise.all(['
        end = '        if (!Array.isArray(followupData.items)'
        if runtime.count(start) != 1 or runtime.count(end) != 1:
            raise ValueError('cloud_event_snapshot_anchor_requires_review')
        before, rest = runtime.split(start, 1)
        runtime = before + ("        const { events, stats, followups: followupData } = "
            "await ZhiweiAdminRequest.json('/api/v1/patrol/workbench')\n") + end + rest.split(end, 1)[1]
        runtime = runtime.replace("link.href = '/admin#work'", "link.href = '/cloud/admin#work'")
        self.responses = {'/cloud/admin': (html.encode(), 'text/html'),
            '/cloud/admin/runtime.js': (runtime.encode(), 'text/javascript'),
            '/assets/service-shell.css': ((static / 'service-shell.css').read_bytes(), 'text/css'),
            '/assets/service/service-mark.svg': ((static / 'service-mark.svg').read_bytes(), 'image/svg+xml')}
        css, mime = self.responses['/assets/service-shell.css']
        css += b'\n.service-tabs{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));width:100%;max-width:none;overflow:visible}.service-tabs a{min-width:0;text-align:center;justify-content:center;padding-inline:8px}#cloudPresentationForm label{display:grid;gap:8px;margin-block:16px}#cloudPresentationForm input,#cloudPresentationForm textarea,#cloudPresentationForm select{width:100%}@media(max-width:680px){.service-tabs{grid-template-columns:repeat(3,minmax(0,1fr))}}\n'
        css += b'.service-quota-table td>strong,.service-quota-table td>span{display:block}.service-quota-table td>strong{margin-top:8px}@media(max-width:680px){.service-quota-scroll{overflow:visible}.service-quota-table{display:block;width:100%;min-width:0}.service-quota-table caption{display:block;text-align:left}.service-quota-table thead{display:none}.service-quota-table tbody{display:grid;gap:12px}.service-quota-table tr{display:grid;grid-template-columns:1fr;padding:10px;border:1px solid #d9e5df;border-radius:12px}.service-quota-table th,.service-quota-table td{display:block;border:0}}\n'
        self.responses['/assets/service-shell.css'] = (css, mime)
        self.responses['/cloud/admin/presentation.js'] = ((WEB / 'presentation.js').read_bytes(), 'text/javascript')
        self.responses['/cloud/admin/robots.js'] = ((WEB / 'robots.js').read_bytes(), 'text/javascript')
        self.responses['/assets/service-shell.css'] = (self.responses['/assets/service-shell.css'][0] +
            b'\n.service-tabs{grid-template-columns:repeat(7,minmax(0,1fr))}@media(max-width:680px){.service-tabs{grid-template-columns:repeat(2,minmax(0,1fr))}}\n' +
            (WEB / 'robots.css').read_bytes() + (WEB / 'module-loading.css').read_bytes(), 'text/css')
        for name in SCRIPTS + (('governance.js',) if governance else ()):
            script = (static / name).read_text(encoding='utf-8')
            if name == 'estate-management.js':
                start = '  let resourcesReading = false'
                if script.count(start) != 1:
                    raise ValueError('cloud_admin_resource_anchor_requires_review')
                script = script.split(start, 1)[0] + '})()\n'
                script = script.replace("`quota${refresh ? '?refresh=true' : ''}`", "'quota'")
            if name == 'api-quota.js':
                script = (WEB / 'quota-compact.js').read_text(encoding='utf-8')
            if name == 'workspace-navigation.js':
                script = script.replace('avatar: [] }', 'avatar: [], robots: [] }')
            if name == 'governance.js':
                script = script.replace('已檢查資料庫及隔離復原；不包含相片原檔、金鑰、模型或機體控制設定，亦未取代正式資料。',
                    '包括已保存的巡查相片；金鑰、模型及機體控制設定分開保留。復原前須再核對現行清除紀錄及用量，不會自動替換正式資料。')
            self.responses['/cloud/admin/' + name] = (
                ("import { cloudFetch as fetch } from '/cloud/admin-request.js'\n" + script).encode(), 'text/javascript')

    def get(self, path):
        return self.responses.get(path)
