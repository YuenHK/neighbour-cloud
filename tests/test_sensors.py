import pytest

from edge_hub.sensors import EnvironmentSensorSimulator


def test_leak_requires_500_ms_sustained_signal() -> None:
    sensors = EnvironmentSensorSimulator.default()

    assert sensors.update_leak(0.9, 1000) is False
    assert sensors.update_leak(0.9, 1499) is False
    assert sensors.update_leak(0.9, 1500) is True
    assert sensors.update_leak(0.9, 1600) is False


def test_dry_reading_resets_leak_debounce() -> None:
    sensors = EnvironmentSensorSimulator.default()

    assert sensors.update_leak(0.9, 0) is False
    assert sensors.update_leak(0.1, 400) is False
    assert sensors.update_leak(0.9, 500) is False
    assert sensors.update_leak(0.9, 999) is False
    assert sensors.update_leak(0.9, 1000) is True


def test_temperature_requires_explicit_safe_drill() -> None:
    sensors = EnvironmentSensorSimulator.default()

    with pytest.raises(ValueError, match="explicitly marked"):
        sensors.update_temperature_drill(40.0, 0, drill=False)
    with pytest.raises(ValueError, match="below 45"):
        sensors.update_temperature_drill(45.0, 0, drill=True)


def test_temperature_drill_requires_500_ms() -> None:
    sensors = EnvironmentSensorSimulator.default()

    assert sensors.update_temperature_drill(40.0, 0, drill=True) is False
    assert sensors.update_temperature_drill(40.0, 500, drill=True) is True
