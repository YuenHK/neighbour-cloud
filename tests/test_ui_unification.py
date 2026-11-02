from collections import Counter
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from edge_hub.app import app
from edge_hub.retired_pages import RETIRED
from edge_hub.ui_shell import service_shell


def test_legacy_pages_redirect_without_serving_old_controls():
    client = TestClient(app)
    for url, target in RETIRED.items():
        response = client.get(url, follow_redirects=False)
        assert response.status_code == 307
        assert response.headers['location'] == target
        assert response.headers['cache-control'] == 'no-store'
        assert '<script' not in response.text


def test_workspace_keeps_real_management_fields_and_removes_duplicate_test_tools():
    class Fields(HTMLParser):
        def __init__(self):
            super().__init__()
            self.ids = []
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if 'id' in attrs:
                self.ids.append(attrs['id'])
    source = (Path(__file__).resolve().parents[1]/'edge_hub/static/admin.html').read_text(encoding='utf-8')
    fields = Fields(); fields.feed(source)
    assert all(count == 1 for count in Counter(fields.ids).values())
    assert {'caseHeading', 'serviceCases', 'knowledgeForm', 'residentMemoriesForm', 'apiQuotaRows', 'operatorKey'} <= set(fields.ids)
    assert not {'chatForm', 'speechForm', 'simulateLitter', 'simulateLeak', 'clearEvents', 'faqForm', 'voiceSettingsForm', 'searchSettingsForm', 'tavilyKey', 'chatModel', 'panel-settings', 'health'} & set(fields.ids)
    rendered = service_shell(source)
    assert 'href="/robots"' in rendered and 'href="/simulation-control"' not in rendered
    assert 'href="/ep-idle-motor-acceptance"' not in rendered
    assert 'data-src="http://127.0.0.1:4173/ui/estate-settings-entry.html"' in rendered
    assert 'title="AIRI 數字人設定"' in rendered
    assert '開啟 AIRI 設定' not in rendered
    assert 'href="http://127.0.0.1:4173/"' not in rendered
    assert 'API key' not in rendered
    assert all(label+'</a>' in rendered for label in ('求助查詢','關懷','現場回報','屋苑資料','服務用量','數字人設定'))
    assert 'class="work-tabs"' not in rendered


def test_robot_workspace_is_the_existing_fleet_page_and_does_not_connect_on_get():
    response = TestClient(app).get('/robots')
    assert response.status_code == 200
    assert 'data-ep-ui="fleet"' in response.text
    assert '<h1>機械人巡邏</h1>' in response.text


def test_robot_drive_header_has_only_relevant_view_controls():
    source = Path('edge_hub/static/ep-fleet.html').read_text(encoding='utf-8')
    header = source.split('<header class="drive-header">', 1)[1].split('</header>', 1)[0]
    assert '居民求助' not in header and 'data-service-pending' not in header
    assert 'fullScreenViews' in header and 'closeDrive' in header


def test_resident_privacy_is_in_topbar_next_to_staff_not_over_the_avatar():
    source = Path('edge_hub/static/resident.html').read_text(encoding='utf-8')
    rendered = service_shell(source)
    topbar = rendered.split('<header class="resident-topbar">',1)[1].split('</header>',1)[0]
    assert 'resident-topbar-actions' in topbar and '資料與私隱' in topbar and '職員入口' in topbar
    main = rendered.split('<main',1)[1].split('</main>',1)[0]
    assert 'resident-privacy-notice' not in main
    assert '鄰伴' in topbar and 'ESTATE SERVICE DESK' not in rendered


def test_workbench_has_no_staff_name_sound_toggle_refresh_or_capacity_estimate():
    source = Path('edge_hub/static/admin.html').read_text(encoding='utf-8')
    for identity in ('staffName','caseSound','refreshCases','quotaCapacity'):
        assert f'id="{identity}"' not in source
    assert 'apiQuotaRows' in source and 'quotaFunctions' in source
