"""Pure opt-in transformation for an isolated AIRI cloud frontend build.

Does not write native vendor files, build output or restart any service.
The native SenseVoice path remains the branch when cloud boot is absent.
"""


def resident_page(source):
    newline = '\r\n' if '\r\n' in source else '\n'
    marker = 'const cloudResidentInput = Reflect.get(globalThis, \'__NEIGHBOUR_CLOUD__\') === true'
    old = 'const voiceTurn = new VoiceTurn(async (audio) => {' + newline
    new = marker + newline + old + (
        '  if (cloudResidentInput) {\n'
        '    if (!estateMode || !residentPanel.value)\n'
        "      throw new Error('cloud_resident_entry_required')\n"
        '    return residentPanel.value.transcribeAudio(audio)\n'
        '  }\n').replace('\n', newline)
    if new in source:
        return source
    if marker in source or source.count(old) != 1:
        raise ValueError('cloud_frontend_input_anchor_requires_review')
    return source.replace(old, new, 1)


def cloud_main(source):
    """Keep the cloud resident build on its sole supported Vue route.

    The caller separately replaces App/profile with cloud-only counterparts.
    Native source/build remains byte-for-byte unchanged after verification.
    """
    replacements = {
        'const routeRecords = setupLayouts(routes as RouteRecordRaw[])':
            "const routeRecords = setupLayouts((routes as RouteRecordRaw[]).filter(route => route.path === '/'))",
        'history: createWebHistory()': "history: createWebHistory('/cloud/resident')",
        "import '@proj-airi/font-cjkfonts-allseto/index.css'": '// Cloud uses the service desk system font.',
        "import '@proj-airi/font-xiaolai/index.css'": '// No 50 MB font preload in the cloud entry.',
    }
    for old, new in replacements.items():
        if new in source:
            continue
        if source.count(old) != 1:
            raise ValueError('cloud_frontend_main_anchor_requires_review')
        source = source.replace(old, new, 1)
    return source


def cloud_scene(source):
    """Remove native-only instrumentation and the unused 100 MB DB stub.

    Keep animation, lip sync, the resident PCM graph and rendering intact.
    """
    newline = '\r\n' if '\r\n' in source else '\n'
    for old in (
        "import { useDuckDb } from '../../composables/use-duck-db'\n",
        "import { useIOTraceBridge } from '../../composables/use-io-trace-bridge'\n",
        "import { initIOTracer } from '../../composables/use-io-tracer'\n",
        "import { useSpeechPipelineAnalytics } from '../../composables/use-speech-pipeline-analytics'\n",
        'const { getDb } = useDuckDb()\n',
        'initIOTracer()\n', 'useIOTraceBridge(speechPipeline)\n', 'useSpeechPipelineAnalytics()\n',
        'void speechRuntimeStore.registerHost(speechPipeline)\n',
        'onMounted(async () => {\n  await getDb() // stub for future update\n})\n',
    ):
        old = old.replace('\n', newline)
        if source.count(old) != 1:
            raise ValueError('cloud_frontend_scene_anchor_requires_review')
        source = source.replace(old, '', 1)
    while newline * 3 in source:
        source = source.replace(newline * 3, newline * 2)
    return source
