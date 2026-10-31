from html.parser import HTMLParser

from deploy.cloud.admin_assets import CloudAdminAssets
from deploy.cloud.web_assets import CloudWebAssets


class Sections(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stack = []
        self.ids = set()
        self.scripts = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if 'id' in values:
            assert values['id'] not in self.ids
            self.ids.add(values['id'])
        if tag == 'section':
            self.stack.append(tag)
        if tag == 'script':
            self.scripts.append(values)

    def handle_endtag(self, tag):
        if tag == 'section':
            assert self.stack
            self.stack.pop()


def test_cloud_workbench_reuses_required_controls_without_native_settings_or_background():
    assets = CloudAdminAssets()
    data, mime = assets.get('/cloud/admin')
    assert mime == 'text/html'
    html = data.decode()
    parser = Sections()
    parser.feed(html)
    assert not parser.stack
    for required in ('tab-work', 'tab-care', 'tab-reports', 'tab-knowledge', 'tab-usage',
                     'tab-avatar', 'panel-avatar', 'cloudAiriSettings',
                     'serviceCases', 'knowledgeForm', 'apiQuotaRows', 'caseAlert'):
        assert required in parser.ids
    assert parser.scripts == [{'type': 'module', 'src': '/cloud/admin-entry.js'}]
    assert 'microphone \'none\'; camera \'none\'; autoplay \'none\'' in html
    for native in ('airiSettingsFrame', 'localResourcesCard', '__LOCAL_OPERATOR_TOKEN__',
                   'ep-background.js', '127.0.0.1', '__SERVICE_SHELL__', '<script>'):
        assert native not in html
    assert assets.get('/cloud/admin/governance.js') is None
    assert assets.get('/cloud/admin/estate-management.js')[0].find(b'loadResources') == -1
    assert b'?refresh=true' not in assets.get('/cloud/admin/estate-management.js')[0]
    assert b"link.href = '/cloud/admin#work'" in assets.get('/cloud/admin/runtime.js')[0]
    assert b'grid-template-columns:repeat(6,minmax(0,1fr))' in assets.get('/assets/service-shell.css')[0]
    assert '官方免費額度</th>' not in html
    assert '免費配額與可用量' in html


def test_stage_cannot_load_staff_ui_and_production_staff_cannot_capture_mic():
    assets = CloudWebAssets()
    response = assets.response('/cloud/admin', storage_acceptance=True, client_id='public')
    assert response.status_code == 423
    response = assets.response('/cloud/admin', storage_acceptance=False, client_id='public')
    assert response.status_code == 200
    assert response.headers['permissions-policy'] == 'microphone=(), camera=(), autoplay=(self)'
    assert "frame-ancestors 'self'" in response.headers['content-security-policy']


def test_formal_governance_assets_describe_cloud_photos_and_current_ledger_restore():
    assets = CloudAdminAssets(governance=True)
    content = assets.get('/cloud/admin/governance.js')[0].decode()
    assert '包括已保存的巡查相片' in content
    assert '不包含相片原檔' not in content
    assert 'import { cloudFetch as fetch }' in content
    assert '復原前須再核對現行清除紀錄及用量' in content
