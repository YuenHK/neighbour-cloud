"""Read-only local probe evidence, not SDK execution or permission to use hardware."""
import hashlib
import re
import sys

from edge_hub.deployment import read_evidence_object

SDK_COMMIT = 'ff6646e115ab125af3207a4ed3df42cc76c795b2'
VERSIONS = {'av': '19.0.2', 'numpy': '2.5.2', 'opencv-python-headless': '4.14.0.94',
            'ifaddr': '0.2.0', 'netaddr': '1.3.0'}


def _hashes_match(directory, declared):
    files = sorted(directory.glob('*.py'))
    if not files or len(files) > 100 or not isinstance(declared, dict):
        return False
    if set(declared) != {path.name for path in files}:
        return False
    for path in files:
        if path.is_symlink():
            return False
        with path.open('rb') as source:
            raw = source.read(512_001)
        if len(raw) > 512_000 or declared[path.name] != hashlib.sha256(raw).hexdigest():
            return False
    return True


def runtime_evidence(root):
    """A mutable local report + source hashes, NOT signed or live runtime attestation."""
    path = root / '.runtime/ep-sdk/validated-runtime.json'
    try:
        if path.is_symlink():
            return 'unavailable'
        with path.open('rb') as source:
            data = read_evidence_object(source.read(64_001), max_bytes=64_000)
        if (data.get('schema') != 'ep-isolated-runtime-probe-v1'
                or data.get('status') != 'adapted_import_and_synthetic_codecs_passed'
                or data.get('runtime_kind') != 'project_adapted_official_source_not_original_wheel'
                or data.get('sdk_source_commit') != SDK_COMMIT
                or data.get('versions') != VERSIONS
                or data.get('python') != '.'.join(map(str, sys.version_info[:3]))
                or any(data.get(key) is not True for key in
                       ('source_pristine', 'sdk_import_tested', 'socket_guard_verified'))
                or any(data.get(key) is not False for key in
                       ('robot_initialized', 'robot_contacted', 'hardware_acceptance',
                        'live_video_verified', 'live_audio_verified', 'live_control_verified'))
                or type(data.get('synthetic_h264_frames')) is not int
                or data['synthetic_h264_frames'] != 3
                or type(data.get('synthetic_opus_packets')) is not int
                or not 1 <= data['synthetic_opus_packets'] <= 10):
            return 'incompatible_or_stale'
        wheels = data.get('wheels')
        if not isinstance(wheels, list) or len(wheels) != len(VERSIONS):
            return 'incompatible_or_stale'
        prefixes = {name.replace('-', '_') + '-' + version + '-' for name, version in VERSIONS.items()}
        seen = set()
        for wheel in wheels:
            if (not isinstance(wheel, dict) or wheel.get('pypi_hash_matches') is not True
                    or not isinstance(wheel.get('filename'), str)
                    or not isinstance(wheel.get('sha256'), str)
                    or re.fullmatch('[0-9a-f]{64}', wheel['sha256']) is None):
                return 'incompatible_or_stale'
            matched = [prefix for prefix in prefixes if wheel['filename'].startswith(prefix)]
            if len(matched) != 1 or matched[0] in seen:
                return 'incompatible_or_stale'
            seen.add(matched[0])
        if (not _hashes_match(root / 'ep_runtime', data.get('adapter_sha256'))
                or not _hashes_match(root / '.runtime/ep-sdk/source/src/robomaster',
                                    data.get('sdk_source_sha256'))):
            return 'incompatible_or_stale'
        return 'reported_offline_pass'
    except (OSError, ValueError, TypeError, RecursionError):
        return 'unavailable'
