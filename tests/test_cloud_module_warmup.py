import hashlib
import re

import test_cloud_frontend_assets

from deploy.cloud.web_assets import CloudWebAssets
from tools.cloud_frontend_assets import package

build = test_cloud_frontend_assets.build


def test_root_preloads_code_for_all_three_areas_without_a_hardware_or_api_request(build):
    source, output, proof = build
    (source / 'assets/cloud-settings-abcdefgh.js').write_bytes(b'export const synthetic = true')
    package(source, output, proof)
    web = CloudWebAssets(output, public_resident=True)
    root = web.response('/', storage_acceptance=False, client_id='unused').body.decode()
    assert all('data-neighbour-warm="' + key + '"' in root for key in ('services', 'settings', 'robots'))
    assert 'href="/api/v1/robot/' not in root
    assert 'data-neighbour-warm="settings" href="/assets/cloud-settings-abcdefgh.js"' in root


def test_robot_cache_alias_is_content_addressed_and_only_program_bytes_are_cacheable():
    web = CloudWebAssets()
    matches = [name for name in web.admin.responses if re.fullmatch(r'/cloud/robot-assets/ep-(?:console|fleet)-[a-f0-9]{12}\.js', name)]
    assert len(matches) == 2
    page = web.response('/cloud/robots', storage_acceptance=False, client_id='unused')
    assert page.headers['cache-control'] == 'no-store'
    for name in matches:
        response = web.response(name, storage_acceptance=False, client_id='unused')
        assert 'immutable' in response.headers['cache-control']
        assert hashlib.sha256(response.body).hexdigest().startswith(name.rsplit('-', 1)[-1][:-3])
        assert name in page.body.decode()
    assert web.response('/cloud/robot-assets/ep-console-000000000000.js', storage_acceptance=False, client_id='unused') is None
