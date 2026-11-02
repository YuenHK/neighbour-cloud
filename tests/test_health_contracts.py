from pathlib import Path


def test_health_readiness_wiring_static_only():
    root = Path(__file__).resolve().parents[1]
    helper = (root / 'scripts/health_contracts.ps1').read_text(encoding='utf-8')
    health = (root / 'scripts/health_check.ps1').read_text(encoding='utf-8')
    assert '"person_privacy_accepted"' in helper
    assert '-isnot [bool]' in helper
    assert '$Vision.status -ne "running"' in helper
    assert '$visionReadiness = Get-VisionReadiness $vision' in health
    assert 'elseif ($visionReadiness -eq "ready")' in health
    assert '[OK] Edge Hub to AIRI bridge' not in health
    assert 'bridge identity and AIRI delivery not verified' in health
    # This is not execution of the PowerShell cases or a live service check.
