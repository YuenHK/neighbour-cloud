import json
import sys

import pytest

from tools import run_backend_acceptance, verify_deployment


@pytest.fixture(params=[run_backend_acceptance, verify_deployment])
def cli(request, tmp_path, monkeypatch):
    module = request.param
    if module is run_backend_acceptance:
        monkeypatch.setattr(module, 'run_recorded', lambda root, operation: operation())
    report = tmp_path / 'reports' / 'result.json'
    monkeypatch.setattr(sys, 'argv', [module.__name__, '--report', str(report)])
    function = 'run' if module is run_backend_acceptance else 'check'
    return module, report, function, monkeypatch


def test_existing_report_rejected_before_checks(cli):
    module, report, function, monkeypatch = cli
    report.parent.mkdir()
    report.write_bytes(b'previous evidence\x00')
    def forbidden(*args, **kwargs):
        raise AssertionError('checks must not run when report already exists')
    monkeypatch.setattr(module, function, forbidden)
    with pytest.raises(FileExistsError):
        module.main()
    assert report.read_bytes() == b'previous evidence\x00'


def test_report_created_during_checks_is_never_overwritten(cli):
    module, report, function, monkeypatch = cli
    def check(*args, **kwargs):
        report.parent.mkdir()
        report.write_bytes(b'other completed run')
        return {'passed': True, 'ready': True}
    monkeypatch.setattr(module, function, check)
    with pytest.raises(FileExistsError):
        module.main()
    assert report.read_bytes() == b'other completed run'


@pytest.mark.parametrize('passed', [True, False])
def test_new_report_preserves_result_and_exit_semantics(cli, passed):
    module, report, function, monkeypatch = cli
    result = {'passed': passed, 'ready': passed, 'note': '隔離軟件證據',
              'hardware_acceptance': False}
    monkeypatch.setattr(module, function, lambda *args, **kwargs: result)
    assert module.main() == (0 if passed else 2)
    assert json.loads(report.read_text(encoding='utf-8')) == result
