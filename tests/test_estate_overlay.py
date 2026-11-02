import shutil
from pathlib import Path

from scripts.apply_estate_ui import apply


def test_resident_overlay_is_idempotent_after_vue_formatter(tmp_path):
    project = Path(__file__).resolve().parents[1]
    files = [
        '.vendor/airi/apps/stage-web/src/pages/index.vue',
        '.vendor/airi/apps/stage-web/vite.config.ts',
        '.vendor/airi/packages/stage-ui/src/components/scenes/Stage.vue',
        '.vendor/airi/packages/stage-layouts/src/composables/theme-color.ts',
        'airi_overlay/theme-color-guard.ts.txt',
        'edge_hub/static/service-shell.css', 'edge_hub/static/service-mark.svg',
        *['airi_overlay/'+name for name in ('resident-session.js', 'resident-idle.js', 'resident-response.js', 'resident-service-panel.vue', 'retired-pages.ts')],
    ]
    for name in files:
        destination = tmp_path/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(project/name, destination)
    (tmp_path/'.vendor/airi/apps/stage-web/src/modules').mkdir()
    (tmp_path/'.vendor/airi/apps/stage-web/public').mkdir()
    page = tmp_path/files[0]
    source = page.read_text(encoding='utf-8')
    source = source.replace('<ResidentServicePanel ', '<ResidentServicePanel\n          ')
    page.write_text(source, encoding='utf-8')
    apply(tmp_path)
    first = page.read_text(encoding='utf-8')
    apply(tmp_path)
    assert page.read_text(encoding='utf-8') == first
    assert first.count('<ResidentServicePanel') == 1
    assert first.count('import ResidentServicePanel from') == 1
    assert '@end-session="resetResidentInput"' in first
