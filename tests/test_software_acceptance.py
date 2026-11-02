from tools.run_software_acceptance import run_acceptance


def test_software_acceptance_is_repeatable_and_clearly_simulated() -> None:
    result = run_acceptance(iterations=10)

    assert result["leak_wet_confirmed"] == 10
    assert result["leak_dry_rejected"] == 10
    assert result["disconnect_safe_stop"] == 10
    assert result["passed"] is True
    assert result["hardware_acceptance"] is False
