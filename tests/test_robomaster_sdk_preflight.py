import pytest

from tools.check_robomaster_sdk import assess, compatible_wheel


@pytest.mark.parametrize("tag,expected", [
    ("cp38-cp38-win_amd64", False),
    ("cp312-cp312-win_amd64", True),
    ("cp312-cp312-manylinux2014_x86_64", False),
    ("cp38-abi3-win_amd64", True),
    ("cp313-abi3-win_amd64", False),
    ("py3-none-any", True),
    ("cp312-cp312-win32", False),
    ("cp36-cp36m-win_amd64", False),
])
def test_native_tags(tag, expected):
    assert compatible_wheel(f"robomaster-1.0-{tag}.whl", 3, 12, "win_amd64") is expected


def test_assessment_is_not_install_or_hardware_proof():
    report = assess({"info": {"name": "robomaster", "version": "1"}, "urls": [{
        "filename": "robomaster-1-cp38-cp38-win_amd64.whl",
        "digests": {"sha256": "abc"},
    }]}, 3, 12, "win_amd64")
    assert report["status"] == "blocked_native_wheel_abi"
    assert report["artifacts"][0]["sha256"] == "abc"
    for field in ("sdk_import_tested", "sdk_installed", "robot_initialized", "hardware_acceptance"):
        assert report[field] is False


def test_yanked_wheel_is_not_available():
    report = assess({"info": {"name": "robomaster"}, "urls": [{
        "filename": "robomaster-1-cp312-cp312-win_amd64.whl", "yanked": True,
    }]}, 3, 12, "win_amd64")
    assert not report["compatible_binary_available"]


def test_wrong_metadata_rejected():
    with pytest.raises(ValueError):
        assess({"info": {"name": "other"}}, 3, 12, "win_amd64")
