import hashlib
import json
from pathlib import Path

from deploy.cloud.frontend_wiring import (
    cloud_display_models,
    cloud_free_model_preview,
    cloud_free_model_runtime,
    cloud_free_model_selector_labels,
    cloud_free_stage_model,
    cloud_model_panel,
    cloud_scene,
)

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / '.vendor/airi/packages/stage-ui/src'


def test_cloud_only_renderer_has_distinct_type_and_never_selects_official_spine_runtime():
    source = (UI / 'stores/settings/stage-model.ts').read_text(encoding='utf-8')
    rendered = cloud_free_stage_model(source)
    assert "case DisplayModelFormat.RigbyJsonZip:\n        return 'rigby'" in rendered
    assert "case DisplayModelFormat.SpineZip:\n        return 'disabled'" in rendered
    assert "return 'spine'" in source  # Native source itself remains unchanged.
    selector = cloud_free_model_selector_labels((UI / 'components/scenarios/dialogs/model-selector/model-selector.vue').read_text(encoding='utf-8'))
    assert "[DisplayModelFormat.RigbyJsonZip]: 'Rigby JSON'" in selector
    display = cloud_display_models((UI / 'stores/display-models.ts').read_text(encoding='utf-8'))
    assert "RigbyJsonZip = 'rigby-json-zip'" in display
    assert "import('../libs/free-skeletal-zip')" in display
    assert "import('@proj-airi/stage-ui-spine" not in display


def test_actual_resident_and_settings_preview_use_free_renderer_and_existing_audio_graph():
    resident = cloud_scene((UI / 'components/scenes/Stage.vue').read_text(encoding='utf-8'))
    assert '<FreeSkeletalScene' in resident and '<SpineScene' not in resident
    assert 'stage-ui-spine' not in resident
    assert ':audio-source="currentAudioSource"' in resident and ':now-speaking="nowSpeaking"' in resident
    assert 'freeSkeletalSceneRef.value?.setEmotion' in resident
    preview = cloud_free_model_preview((UI / 'components/scenarios/settings/model-settings/preview-stage.vue').read_text(encoding='utf-8'))
    assert '<FreeSkeletalScene' in preview and '<SpineScene' not in preview
    assert "renderer: 'rigby'" in preview and 'stage-ui-spine' not in preview
    runtime = cloud_free_model_runtime((UI / 'components/scenarios/settings/model-settings/runtime.ts').read_text(encoding='utf-8'))
    assert "'vrm' | 'rigby'" in runtime
    panel = cloud_model_panel((UI / 'components/scenarios/settings/model-settings/panel.vue').read_text(encoding='utf-8'))
    assert '<details class="cloud-model-options" open>' in panel
    assert '<Spine' not in panel and "import Spine" not in panel and 'effectiveRenderer === \'rigby\'' in panel


def test_fixed_runtime_source_and_distributed_notices_are_exactly_retained():
    directory = ROOT / 'airi_overlay/free-skeletal-runtime'
    receipt = json.loads((directory / 'PROVENANCE.json').read_text(encoding='utf-8'))
    assert receipt['commit'] == '72bc84625fac4959e185574df12adbd33add11d6'
    for row in receipt['files']:
        raw = (directory / row['path']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        if row['path'].endswith('.js'):
            assert raw.startswith(b'// SPDX-License-Identifier: MIT OR Apache-2.0')
            assert b'@esotericsoftware' not in raw
    notice = (ROOT / 'deploy/cloud/web/free-skeletal-notices.txt').read_text(encoding='utf-8')
    assert (directory / 'LICENSE-MIT').read_text(encoding='utf-8') in notice
    assert (directory / 'LICENSE-APACHE').read_text(encoding='utf-8') in notice
    assert (directory / 'THIRD_PARTY_NOTICES.md').read_text(encoding='utf-8') in notice
