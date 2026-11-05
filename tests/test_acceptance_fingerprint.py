from tools.acceptance_gate import fingerprint


def test_es_module_regression_change_invalidates_source_gate(tmp_path):
    directory = tmp_path/'tests'
    directory.mkdir()
    script = directory/'new-renderer.test.mjs'
    script.write_bytes(b'assert.equal(render(), true)')
    before = fingerprint(tmp_path)
    script.write_bytes(b'assert.equal(render(), false)')
    assert fingerprint(tmp_path) != before
