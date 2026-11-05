"""No-hardware, isolated SDK import and synthetic codec verification.

Online provenance queries only fixed PyPI metadata URLs BEFORE installing the
no-socket audit guard. No SDK constructors, initialization or robot discovery.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.request import urlopen

SDK_COMMIT = 'ff6646e115ab125af3207a4ed3df42cc76c795b2'
PACKAGES = {'av': '19.0.2', 'numpy': '2.5.2', 'opencv-python-headless': '4.14.0.94',
            'ifaddr': '0.2.0', 'netaddr': '1.3.0'}


def no_network(event, args):
    # platform.system()/ifaddr imports read the local hostname on Windows;
    # allow only that non-network query, never DNS/socket creation/connect/bind.
    if ((event.startswith('socket.') and event != 'socket.gethostname')
            or event in {'subprocess.Popen', 'os.system'}):
        raise RuntimeError('offline EP probe forbids sockets and child processes')


def run(root, *, offline=False):
    expected = root / '.runtime/ep-sdk/venv'
    if Path(sys.prefix).resolve() != expected.resolve() or sys.prefix == sys.base_prefix:
        raise RuntimeError('run only with the dedicated EP SDK venv, not AIRI Python')
    source = root / '.runtime/ep-sdk/source'
    commit = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if commit != SDK_COMMIT:
        raise RuntimeError('unexpected official SDK revision')
    subprocess.run(['git', '-C', str(source), 'diff', '--exit-code', 'HEAD', '--', 'src', 'LICENSE'],
                   check=True, capture_output=True)
    versions = {name: importlib.metadata.version(name) for name in PACKAGES}
    if versions != PACKAGES:
        raise RuntimeError('unexpected isolated dependency versions')
    wheels = []
    for name, version in PACKAGES.items():
        prefix = name.replace('-', '_') + '-' + version + '-'
        files = list((root / '.runtime/ep-sdk/wheels').glob(prefix + '*.whl'))
        if len(files) != 1:
            raise RuntimeError('missing or ambiguous wheel')
        wheel = files[0]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        matches = None
        if not offline:
            with urlopen(f'https://pypi.org/pypi/{name}/{version}/json', timeout=15) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError('package metadata too large')
            metadata = json.loads(raw)
            matches = any(item['filename'] == wheel.name and item['digests']['sha256'] == digest
                          and not item.get('yanked') for item in metadata['urls'])
            if not matches:
                raise ValueError('wheel hash did not match fixed PyPI metadata')
        wheels.append({'filename': wheel.name, 'sha256': digest, 'pypi_hash_matches': matches})

    # This process can never contact a robot even if imported SDK code tries.
    sys.addaudithook(no_network)
    import av
    import numpy as np

    from ep_runtime.bootstrap import load_sdk
    from ep_runtime.codecs import H264Decoder, OpusDecoder

    robot, media = load_sdk(source / 'src')
    assert callable(robot.Robot.initialize) and callable(robot.Robot.play_audio)
    # No Robot() / initialize() / LiveView constructor here.
    view = SimpleNamespace(_video_decoder=H264Decoder())
    encoder = av.CodecContext.create('libx264', 'w')
    encoder.width, encoder.height, encoder.pix_fmt = 64, 48, 'yuv420p'
    encoder.thread_count = 2
    encoder.options = {'preset': 'ultrafast', 'tune': 'zerolatency'}
    packets = []
    for value in (0, 64, 128):
        frame = av.VideoFrame.from_ndarray(np.full((48, 64, 3), value, dtype=np.uint8), format='bgr24')
        packets.extend(encoder.encode(frame))
    packets.extend(encoder.encode(None))
    frames = []
    for packet in packets:
        frames.extend(media.LiveView._h264_decode(view, bytes(packet)))
    frames.extend(media.LiveView._h264_decode(view, b''))
    assert len(frames) == 3 and all(frame.shape == (48, 64, 3) for frame in frames)

    opus = av.CodecContext.create('libopus', 'w')
    opus.sample_rate, opus.layout, opus.format = 48000, 'mono', 's16'
    silent = av.AudioFrame.from_ndarray(np.zeros((1, 960), dtype=np.int16), format='s16', layout='mono')
    silent.sample_rate = 48000
    encoded = list(opus.encode(silent)) + list(opus.encode(None))
    decoder = OpusDecoder()
    decoded = [decoder.decode(bytes(packet)) for packet in encoded]
    assert decoded and all(len(packet) == 1920 for packet in decoded)
    try:
        import socket
        socket.socket()
    except RuntimeError as error:
        assert 'forbids sockets' in str(error)
    else:
        raise AssertionError('socket guard did not block')
    return {
        'schema': 'ep-isolated-runtime-probe-v1', 'status': 'adapted_import_and_synthetic_codecs_passed',
        'sdk_source_commit': commit, 'sdk_version': '0.1.1.68', 'python': sys.version.split()[0],
        'runtime_kind': 'project_adapted_official_source_not_original_wheel',
        'source_pristine': True, 'versions': versions, 'wheels': wheels,
        'sdk_import_tested': True, 'synthetic_h264_frames': len(frames),
        'synthetic_opus_packets': len(decoded), 'socket_guard_verified': True,
        'robot_initialized': False, 'robot_contacted': False, 'hardware_acceptance': False,
        'live_video_verified': False, 'live_audio_verified': False, 'live_control_verified': False,
        'scope': 'isolated import and synthetic codecs only; not EP network framing or hardware acceptance',
        'adapter_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                           for path in sorted((root / 'ep_runtime').glob('*.py'))},
        'sdk_source_sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                              for path in sorted((source / 'src/robomaster').glob('*.py'))},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--offline', action='store_true')
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError('preserve previous probe reports')
    result = run(Path(__file__).resolve().parents[1], offline=args.offline)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as output:
        json.dump(result, output, indent=2)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
