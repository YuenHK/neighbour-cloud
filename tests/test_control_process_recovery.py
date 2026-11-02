import subprocess

import pytest

from tools.check_control_process_recovery import run, worker


def test_worker_rejects_non_disposable_or_missing_root(tmp_path):
    with pytest.raises(ValueError, match='disposable'):
        worker('crash', tmp_path)
    assert not (tmp_path / 'robot.sqlite3').exists()


def test_real_child_process_exit_recovers_stopped_without_hardware():
    report = run()
    assert report['passed']
    assert report['scope'] == 'controller-child-process-exit-not-os-or-hardware-restart'
    assert report['hardware_acceptance'] is False
    assert report['production_data_modified'] is False
    assert len(report['checks']) == 7
    assert 'lease_token' not in str(report)


def test_worker_timeout_does_not_report_success_or_dump_child_output(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired('internal-worker', 15, output='private-output')

    monkeypatch.setattr('tools.check_control_process_recovery.subprocess.run', timeout)
    report = run()
    assert report['passed'] is False
    assert report['error_type'] == 'TimeoutExpired'
    assert not any(report['checks'].values())
    assert 'private-output' not in str(report)
