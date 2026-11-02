import os
import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.skipif(os.environ.get('ZHIWEI_RUN_POWERSHELL_CONTRACTS') != '1',
                    reason='PowerShell scripts blocked by host policy; no automatic retry or bypass')
def test_startup_helpers_without_starting_services(tmp_path):
    shell = shutil.which('powershell.exe') or shutil.which('pwsh')
    if shell is None:
        pytest.skip('PowerShell is unavailable')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([shell, '-NoProfile', '-File', str(root / 'tests/airi_startup_contracts.tests.ps1'),
        '-HelperPath', str(root / 'scripts/airi_startup_contracts.ps1'), '-TempRoot', str(tmp_path)],
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'startup contracts passed; no services started or stopped' in result.stdout


def test_launcher_saves_each_launch_before_waiting_and_does_not_trust_old_pid():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/start_airi.ps1').read_text(encoding='utf-8')
    assert 'Get-AiriManagedProcesses' in source
    assert 'Get-Process -Id $existingId' not in source
    for role in ('edgeHub', 'audio', 'server', 'stage', 'bridge'):
        assignment = f'$processes.{role} = ${role}.Id'
        assert assignment + '\n  Save-AiriProcessRegistry $processes $processFile' in source
        assert f"$processes.ContainsKey('{role}')" in source or f'$processes.ContainsKey("{role}")' in source
    assert 'Test-AiriRunnerIdentity $bridgeProcess' in source
    assert '$bridgeReady = Test-AiriBridgeReadyText $bridgeText' in source
    assert 'if (-not $bridgeReady)' in source


def test_startup_helper_readiness_and_identity_contracts_static():
    root = Path(__file__).resolve().parents[1]
    helper = (root / 'scripts/airi_startup_contracts.ps1').read_text(encoding='utf-8')
    bridge = (root / 'airi_bridge/src/index.ts').read_text(encoding='utf-8')
    markers = ('AIRI bridge cursor polling ready; notifications are optional',
               'AIRI local cursor journal ready; page-only transport, not receiver ACK')
    for marker in markers:
        assert marker in helper and marker in bridge
    assert '-ccontains $value' in helper
    assert 'Test-AiriRunnerIdentity' in helper and '[regex]::Escape' in helper
    assert '$matchingRunners.Count -gt 1' in helper
    assert 'Multiple managed $role runners found' in helper
    assert '[System.IO.File]::Replace' in helper
    assert 'Start-Process' not in helper and 'Stop-Process' not in helper


def test_registry_replace_preserves_null_string_for_windows_powershell():
    root = Path(__file__).resolve().parents[1]
    helper = (root / 'scripts/airi_startup_contracts.ps1').read_text(encoding='utf-8')
    assert ('[System.IO.File]::Replace($temporary, $target, '
            '[System.Management.Automation.Language.NullString]::Value)') in helper
    assert '[System.IO.File]::Replace($temporary, $target, $null)' not in helper
    assert '[System.IO.File]::Move($temporary, $target)' in helper
    assert 'Remove-Item -LiteralPath $target' not in helper
