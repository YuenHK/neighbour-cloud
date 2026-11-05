import hashlib
import io
import json
import os
import subprocess
import sys
import zipfile

import pytest

from deploy.cloud.patrol_kit import source_kit
from tools.navigation_board_lab import render_frame, synthetic_calibration


def extract_kit(path):
    with zipfile.ZipFile(io.BytesIO(source_kit())) as archive:
        archive.extractall(path)
    manifest = json.loads((path/'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        assert hashlib.sha256((path/name).read_bytes()).hexdigest() == digest
    assert manifest['hardware_commands'] == 0
    assert not manifest['execution_enabled']


def cli(path, *args):
    env = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([sys.executable, *args], cwd=path, env=env,
                            capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_downloaded_kit_can_replay_all_faults_without_project_checkout(tmp_path):
    extract_kit(tmp_path)
    result = cli(tmp_path, 'navigation_acceptance.py', '--output', 'synthetic-run')
    assert result['passed'] and result['scenarios'] == 8
    assert result['real_hardware_commands'] == 0
    summary = json.loads((tmp_path/'synthetic-run/SUMMARY.json').read_text())
    assert not summary['camera_accuracy_tested'] and not summary['physical_stop_tested']
    assert len(list((tmp_path/'synthetic-run').glob('*.csv'))) == 8
    from tools.navigation_acceptance import run
    with pytest.raises(FileExistsError):
        run(tmp_path/'synthetic-run')


def test_downloaded_kit_explicit_board_mode_reads_saved_synthetic_jpeg(tmp_path):
    extract_kit(tmp_path)
    calibration = synthetic_calibration(nonplanar=True)
    (tmp_path/'calibration.json').write_text(json.dumps(calibration))
    (tmp_path/'saved.jpg').write_bytes(render_frame(calibration, noise=1.5))
    value = cli(tmp_path, 'localisation_replay.py', 'analyse', '--method', 'board',
        '--calibration', 'calibration.json', '--jpeg', 'saved.jpg',
        '--captured-at-ms', '1000', '--now-ms', '1100', '--fixed-camera-confirmed')
    assert value['state'] == 'located'
    assert value['method'] == 'joint_nonplanar_sqpnp'
    assert not value['motion_authorized']
