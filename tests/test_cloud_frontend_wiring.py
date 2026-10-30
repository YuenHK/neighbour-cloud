import pytest

from deploy.cloud.frontend_wiring import cloud_main, resident_page


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


def test_cloud_main_has_one_resident_route_and_no_large_font_preloads():
    source = """const routeRecords = setupLayouts(routes as RouteRecordRaw[])
    history: createWebHistory()
    import '@proj-airi/font-cjkfonts-allseto/index.css'
    import '@proj-airi/font-xiaolai/index.css'
    """
    result = cloud_main(source)
    assert "route.path === '/'" in result and "createWebHistory('/cloud/resident')" in result
    assert 'import ' not in result and cloud_main(result) == result
    with pytest.raises(ValueError):
        cloud_main('upstream changed')
