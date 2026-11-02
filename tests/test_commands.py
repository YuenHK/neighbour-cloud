import pytest

from edge_hub.commands import Command, validate_command


def test_start_patrol_is_allowed() -> None:
    assert validate_command(Command(seq=1, type="start_patrol", ttl_ms=500)).type == "start_patrol"


def test_pwm_is_rejected() -> None:
    with pytest.raises(ValueError, match="not allowed"):
        validate_command(Command(seq=2, type="set_pwm", ttl_ms=500))
