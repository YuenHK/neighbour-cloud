"""Ground local candidate labels in explicit visible cues, not self-rated scores.

This validates the model's *description*, not the pixels. It cannot establish
real-world accuracy, live electricity, identities or criminal intent. Reflection
and uncertainty cues abstain; smoke/electrical candidates still need a person.
"""

CUES = {
    'litter': ('discarded_on_floor', 'overflowing_bin'),
    'standing_water': ('pool_boundary', 'flowing_water', 'active_drip'),
    'smoke_flame': ('visible_smoke', 'visible_flame'),
    'electrical_hazard': ('visible_sparks', 'burnt_socket', 'exposed_damaged_wire'),
    'restricted_presence': ('person_in_marked_area',),
}
ABSTAIN = ('reflection_only', 'uncertain', 'object_in_normal_use')
ALL_CUES = tuple(cue for cues in CUES.values() for cue in cues) + ABSTAIN
CONFIRM_WINDOW_MS = 60_000


def observation_schema():
    return {'type': 'object', 'properties': {'findings': {
        'type': 'array', 'maxItems': 4, 'items': {
            'type': 'object', 'properties': {
                'kind': {'type': 'string', 'enum': list(CUES)},
                'cue': {'type': 'string', 'enum': list(ALL_CUES)}},
            'required': ['kind', 'cue'], 'additionalProperties': False}}},
        'required': ['findings'], 'additionalProperties': False}


def grounded_findings(value, restricted):
    if type(value) is not dict or set(value) != {'findings'}:
        raise ValueError('invalid local observation')
    findings = value['findings']
    if type(findings) is not list or len(findings) > 4:
        raise ValueError('invalid local observation')
    result = set()
    for finding in findings:
        if (type(finding) is not dict or set(finding) != {'kind', 'cue'}
                or type(finding['kind']) is not str or type(finding['cue']) is not str
                or finding['kind'] not in CUES or finding['cue'] not in ALL_CUES):
            raise ValueError('invalid local observation')
        kind, cue = finding['kind'], finding['cue']
        if cue not in CUES[kind] or kind == 'restricted_presence' and not restricted:
            continue
        result.add(kind)
    return result


def same_confirmation_window(state, frame):
    previous, captured = state.get('previous_captured_at_ms'), frame.get('captured_at_ms')
    return (type(previous) is int and type(captured) is int
            and 0 < captured-previous <= CONFIRM_WINDOW_MS
            and state.get('previous_epoch') == frame['key'].split('-')[0]
            and state.get('previous_sn') == frame.get('sn'))
