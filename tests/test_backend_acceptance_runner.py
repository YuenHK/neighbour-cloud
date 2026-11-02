import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.run_backend_acceptance import restored_settings, run


def test_runner_refuses_cached_app_before_changing_paths_or_services(monkeypatch):
    # A cached application may point at real stores; never mutate it for an acceptance run.
    monkeypatch.setattr(os, 'environ', dict(os.environ))
    monkeypatch.setitem(sys.modules, 'edge_hub.app', object())
    before = dict(os.environ)
    with pytest.raises(RuntimeError, match='fresh isolated process'):
        run()
    assert dict(os.environ) == before


def test_fresh_process_acceptance_includes_database_reopen_and_stop_checks(tmp_path):
    # Unit-test disposable DB checks independently of this dirty developer tree's
    # deployment inventory. run_recorded/CLI must STILL refuse stale inventories;
    # test_backend_report_identity covers that gate. Do not forge a real manifest.
    code = ('import json; from tools.run_backend_acceptance import run; '
            'print(json.dumps(run(), ensure_ascii=True))')
    completed = subprocess.run([sys.executable, '-c', code],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True,
                               text=True, encoding='utf-8', timeout=45, check=True)
    result = json.loads(completed.stdout)
    for name in ['reopen_stop_latched', 'reopen_no_lease_or_motion', 'reopen_old_lease_rejected',
                 'reopen_review_persisted', 'reopen_cursor_persisted', 'reopen_reset_stays_stopped',
                 'clear_cursor_and_late_event']:
        assert result['checks'][name]
    assert result['passed'] and not result['hardware_acceptance']
    assert result['restart_scope'] == 'application-reimport-and-sqlite-reopen-not-os-or-process-reboot'


def test_isolated_settings_restored_on_failure(monkeypatch):
    monkeypatch.setenv('ZHIWEI_EVENT_DB', 'existing-database')
    monkeypatch.delenv('ZHIWEI_ROBOT_DB', raising=False)
    with pytest.raises(RuntimeError, match='test interruption'), restored_settings():
        os.environ['ZHIWEI_EVENT_DB'] = 'temporary-database'
        os.environ['ZHIWEI_ROBOT_DB'] = 'temporary-controller'
        raise RuntimeError('test interruption')
    assert os.environ['ZHIWEI_EVENT_DB'] == 'existing-database'
    assert 'ZHIWEI_ROBOT_DB' not in os.environ
