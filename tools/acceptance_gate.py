"""Deterministic pre-release checks. No secrets, providers, formal stores or EP.

CI never deploys. A passing run is necessary, not a substitute for the separate
stopped-writer/schema/backup/release approval protocol.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS = ['test_community_operations.py', 'test_cloud_http_app.py', 'test_cloud_staff_api.py',
         'test_cloud_case_photo.py', 'test_cloud_maintenance.py', 'test_cloud_retention_restore.py',
         'test_cloud_photo_api.py', 'test_cloud_rollout.py', 'test_cloud_frontend_wiring.py', 'test_cloud_frontend_assets.py',
         'test_resident_case_continuity.py', 'test_cantonese_routing_corpus.py',
         'test_cantonese_multiturn.py', 'test_azure_stream_arrival.py',
         'test_resident_pcm_stream.py', 'test_hardware_agent.py', 'test_patrol_schedule.py',
         'test_ep_patrol.py', 'test_cloud_web_assets.py', 'test_workbench_filters.py',
         'test_cloud_admin_assets.py', 'test_service_desk.py', 'test_cloud_avatar_vrm.py',
         'test_cloud_avatar_assets.py', 'test_cloud_avatar_api.py', 'test_cloud_presentation.py',
         'test_cloud_gallery_catalog.py', 'test_cloud_vroid_api.py', 'test_cloud_vroid_library.py']


def fingerprint(root):
    from tools.cloud_bundle import source_files
    files = {relative.as_posix(): path for relative, path in source_files(root)}
    for directory in ('tests', '.github/workflows'):
        for path in (root / directory).rglob('*'):
            if path.is_file() and path.suffix in ('.py', '.json', '.cjs', '.yml', '.yaml'):
                files[path.relative_to(root).as_posix()] = path
    return hashlib.sha256(json.dumps([(name, hashlib.sha256(path.read_bytes()).hexdigest())
        for name, path in sorted(files.items())], separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default='acceptance-results')
    parser.add_argument('--network-faults', action='store_true')
    parser.add_argument('--browser', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    before = fingerprint(root)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, 'PYTHONPATH': str(root), 'NO_PROXY': '127.0.0.1,localhost',
           'PROMPTFOO_DISABLE_TELEMETRY': '1', 'PYTHONIOENCODING': 'utf-8', 'PROMPTFOO_PYTHON': sys.executable}
    commands = [['python', '-m', 'pytest', *['tests/' + name for name in TESTS],
                 '-q', '--junitxml=' + str(output / 'regression.xml')],
                ['node', '--test', 'tests/resident-pcm.test.cjs', 'tests/resident-avatar-audio.test.cjs', 'tests/resident-camera.test.cjs', 'tests/staff-pwa.test.cjs',
                 'tests/cloud-transport.test.cjs', 'tests/admin-request.test.cjs', 'tests/workbench-live.test.cjs', 'tests/model-dedup.test.cjs',
                 'tests/cloud-privacy.test.cjs']]
    commands[0][0] = sys.executable
    if args.network_faults:
        commands.append([sys.executable, 'tools/toxiproxy_acceptance.py', '--output', str(output / 'network.json')])
    if args.browser:
        commands.append(['node', 'tests/acceptance/workbench-mobile.browser.cjs'])
    node_modules = Path(os.environ.get('NODE_PATH') or root / '.experiments/optimization-lab-20261029/node/node_modules')
    package = json.loads((node_modules / 'promptfoo/package.json').read_text(encoding='utf-8'))
    binary = package['bin']['promptfoo'] if isinstance(package['bin'], dict) else package['bin']
    commands.append(['node', str(node_modules / 'promptfoo' / binary), 'eval', '--config',
        str(root / 'tools/evaluation/promptfooconfig.json'), '--no-cache', '--no-table', '--output', str(output / 'promptfoo.json')])
    results = []
    for index, command in enumerate(commands):
        started = time.monotonic()
        with (output / f'check-{index}.log').open('wb') as log:
            completed = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=600, check=False)
        results.append({'index': index, 'exit': completed.returncode, 'elapsed_seconds': round(time.monotonic()-started, 3)})
        if completed.returncode:
            break
    passed = len(results) == len(commands) and all(row['exit'] == 0 for row in results)
    after = fingerprint(root)
    passed = passed and before == after
    (output / 'result.json').write_text(json.dumps({'passed': passed, 'checks': results,
        'source_sha256': before, 'source_unchanged_during_checks': before == after,
        'completed_at': time.time(), 'real_providers': False, 'real_hardware': False,
        'deployment_authorized_by_this_result': False}, indent=2))
    print(json.dumps({'passed': passed, 'checks': results}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
