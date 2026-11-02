from tools.mechanical_budget import required_torque_per_side


def test_required_torque_uses_safety_factor() -> None:
    torque = required_torque_per_side(
        mass_kg=3.5,
        incline_deg=26.565,
        drive_radius_m=0.04,
        safety_factor=3.0,
    )
    assert 0.90 < torque < 0.94
