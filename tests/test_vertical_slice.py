from tools.run_vertical_slice import run_demo


def test_demo_produces_safe_ordered_events() -> None:
    result = run_demo()
    assert result["states"] == ["patrol", "stair_ascend", "patrol"]
    assert result["event"]["type"] == "litter_detected"
    assert result["event"]["evidence"].endswith("-blurred.jpg")
    assert "疑似新垃圾" in result["airi_text"]
