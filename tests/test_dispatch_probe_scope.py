from pathlib import Path


def test_legacy_event_probe_does_not_claim_receiver_or_ui_acceptance():
    script = (Path(__file__).resolve().parents[1] / 'scripts/test_event_delivery.ps1').read_text(encoding='utf-8')
    assert 'not AIRI acknowledgement' in script
    assert 'not UI end-to-end' in script
    assert 'Published to AIRI:' not in script
    assert '"End-to-end latency:' not in script
