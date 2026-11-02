"""Read-only regression checks; never execute startup or deployment scripts."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_local_inventory_supports_same_source_without_copying_itself():
    script = (ROOT / 'scripts/sync_to_local_deployment.ps1').read_text(encoding='utf-8-sig')
    assert '$inPlace = $destinationFull.Equals($source,' in script
    assert 'Source and deployment destination must be different' not in script
    assert 'if (-not $inPlace) {' in script
    assert "workspace_mode = $(if ($inPlace) { 'local-primary' }" in script


def test_inventory_includes_unsynced_sources_but_not_temporary_downloads():
    script = (ROOT / 'scripts/sync_to_local_deployment.ps1').read_text(encoding='utf-8-sig')
    assert 'ls-files --cached --others --exclude-standard' in script
    assert 'Where-Object' in script and "^tmp[/" in script
    assert 'if ($InstallDependencies)' in script


def test_deploy_defaults_to_inventory_without_policy_bypass_or_install():
    launcher = (ROOT / 'DEPLOY-AIRI.cmd').read_text(encoding='utf-8-sig')
    assert '-InstallDependencies' not in launcher
    assert '-ExecutionPolicy' not in launcher
    assert 'sync_to_local_deployment.ps1" %*' in launcher


def test_future_workspace_instructions_use_local_primary():
    instructions = (ROOT / 'AGENTS.md').read_text(encoding='utf-8')
    assert r'C:\Users\Maker\Projects\AIRI-Project' in instructions
    assert 'UNO R3' in instructions
    assert '不自動行路' in instructions
