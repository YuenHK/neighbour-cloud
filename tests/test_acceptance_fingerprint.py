from tools.acceptance_gate import fingerprint


def test_es_module_regression_change_invalidates_source_gate(tmp_path):
    directory = tmp_path/'tests'
    directory.mkdir()
    script = directory/'new-renderer.test.mjs'
    script.write_bytes(b'assert.equal(render(), true)')
    before = fingerprint(tmp_path)
    script.write_bytes(b'assert.equal(render(), false)')
    assert fingerprint(tmp_path) != before


def test_gate_exports_verified_node_dependency_root_to_browser_children(monkeypatch, tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    from tools import acceptance_gate
    captured = []
    monkeypatch.delenv('NODE_PATH', raising=False)
    monkeypatch.setattr(acceptance_gate, 'fingerprint', lambda root: 'synthetic-environment-test-not-a-release')
    monkeypatch.setattr(acceptance_gate.sys, 'argv', ['acceptance_gate.py', '--output', str(tmp_path), '--network-faults', '--browser'])
    def fake_run(command, **kwargs):
        captured.append((command, kwargs['env']))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(acceptance_gate.subprocess, 'run', fake_run)
    assert acceptance_gate.main() == 0
    assert len(captured) == 5
    expected = Path(acceptance_gate.__file__).resolve().parents[1] / '.experiments/optimization-lab-20261029/node/node_modules'
    for command, environment in captured:
        assert Path(environment['NODE_PATH']).resolve() == expected.resolve()
        assert environment['PROMPTFOO_DISABLE_TELEMETRY'] == '1'
