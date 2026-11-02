"""Original console program with an authenticated same-origin transport."""
import hashlib
import re
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / 'edge_hub/static'


def robot_assets():
    page = (STATIC / 'ep-fleet.html').read_text(encoding='utf-8')
    page = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', page)
    page = page.replace('__SERVICE_SHELL__', '').replace('__LOCAL_OPERATOR_TOKEN__', 'cloud-managed-control-session')
    page = page.replace('data-ep-ui="fleet"', 'data-ep-ui="fleet" data-hardware-only="true"')
    page = page.replace('href="/assets/ep-', 'href="/cloud/robot-assets/ep-')
    page = page.replace('</body>', '<script type="module" src="/cloud/robot-entry.js"></script></body>')
    responses = {'/cloud/robots': (page.encode(), 'text/html')}
    for name in ('ep-fleet.js', 'ep-console.js', 'ep-fleet.css', 'ep-console.css'):
        data = (STATIC / name).read_text(encoding='utf-8')
        if name.endswith('.js'):
            data = "import { cloudFetch as fetch } from '/cloud/admin-request.js'\n" + data
            data = data.replace("fetch('/robots'", "globalThis.fetch('/cloud/robots'")
        if name == 'ep-fleet.css':
            data += '\n.fleet-console{max-width:none;padding:12px}.fleet-console>.service-heading-row{display:none}\n'
        responses['/cloud/robot-assets/' + name] = (data.encode(), 'text/javascript' if name.endswith('.js') else 'text/css')
    preloads = []
    for kind in ('console', 'fleet'):
        data, mime = responses['/cloud/robot-assets/ep-' + kind + '.js']
        alias = '/cloud/robot-assets/ep-' + kind + '-' + hashlib.sha256(data).hexdigest()[:12] + '.js'
        responses[alias] = (data, mime)
        preloads.append('<link rel="modulepreload" data-robot-script="' + kind + '" href="' + alias + '">')
    responses['/cloud/robots'] = (page.replace('</head>', ''.join(preloads) + '</head>', 1).encode(), 'text/html')
    return responses
