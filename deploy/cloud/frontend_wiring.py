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
