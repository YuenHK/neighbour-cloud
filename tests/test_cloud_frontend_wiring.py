import pytest

from deploy.cloud.frontend_wiring import cloud_audio_device, cloud_main, resident_page


@pytest.mark.parametrize('newline', ['\n', '\r\n'])
def test_cloud_branch_preserves_native_audio_and_original_line_endings(newline):
    source = ('PREFIX' + newline + 'const voiceTurn = new VoiceTurn(async (audio) => {' + newline
              + '  return transcribeForRecording(audio)' + newline + '})' + newline)
    value = resident_page(source)
    assert resident_page(value) == value
    assert value.startswith('PREFIX' + newline) and value.endswith('})' + newline)
    assert 'return residentPanel.value.transcribeAudio(audio)' in value
    assert 'return transcribeForRecording(audio)' in value
    assert value.index('if (cloudResidentInput)') < value.index('return transcribeForRecording')
    if newline == '\r\n':
        assert '\n' not in value.replace('\r\n', '')


def test_changed_or_ambiguous_vendor_source_requires_review():
    with pytest.raises(ValueError):
        resident_page('different upstream entry')


def test_cloud_mic_enable_is_local_to_one_frame_not_shared_with_staff_or_next_tab():
    source = "  const audioInputEnabled = useLocalStorageManualReset<boolean>('settings/audio/input/enabled', false)\n"
    value = cloud_audio_device(source)
    assert 'useLocalStorage' not in value
    assert 'refManualReset<boolean>' in value and "get('settings') !== '1'" in value
    assert cloud_audio_device(value) == value


def test_cloud_main_keeps_settings_routes_in_staff_memory_history_only():
    source = """const routeRecords = setupLayouts(routes as RouteRecordRaw[])
    history: createWebHistory()
    import '@proj-airi/font-cjkfonts-allseto/index.css'
    import '@proj-airi/font-xiaolai/index.css'
    void bootstrapLocalProfile()
    import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router'
    """
    result = cloud_main(source)
    assert "route.path === '/'" in result and "createWebHistory('/cloud/resident')" in result
    assert 'cloudSettingsMode ? createMemoryHistory()' in result
    assert "route.path.startsWith('/settings')" in result
    assert 'font-xiaolai/index.css' not in result and cloud_main(result) == result
    with pytest.raises(ValueError):
        cloud_main('upstream changed')
