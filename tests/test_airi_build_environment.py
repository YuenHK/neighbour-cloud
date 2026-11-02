from pathlib import Path


def test_build_resolves_git_before_invoking_vite():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/apply_airi_local_profile.ps1').read_text(encoding='utf-8')
    assert source.index('Initialize-AiriBuildEnvironment') < source.index('& $projectPnpm --filter @proj-airi/stage-web build')
    helper = (root / 'scripts/airi_build_environment.ps1').read_text(encoding='utf-8')
    assert 'Get-Command git.exe -CommandType Application' in helper
    assert 'HKCU:\\SOFTWARE\\GitForWindows' in helper
    assert 'HKLM:\\SOFTWARE\\GitForWindows' in helper
    assert "-PathType Leaf" in helper
    assert '& $gitPath --version' in helper
    assert '$LASTEXITCODE -ne 0' in helper
    assert '$env:Path = (Split-Path -Parent $gitPath)' in helper
    for forbidden in ('SetEnvironmentVariable', 'setx', 'Start-Process', 'ExecutionPolicy', 'Invoke-Expression'):
        assert forbidden not in helper


def test_git_preflight_runs_only_when_a_build_is_needed():
    root = Path(__file__).resolve().parents[1]
    source = (root / 'scripts/apply_airi_local_profile.ps1').read_text(encoding='utf-8')
    assert "if ($needsBuild -and -not $SkipBuild) {\n  . (Join-Path $PSScriptRoot 'airi_build_environment.ps1')" in source
    assert source.index('Initialize-AiriBuildEnvironment') < source.index('$overlayHash | Set-Content')
