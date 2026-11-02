from tools.build_combined_litter_dataset import split_scenes


def test_split_scenes_is_deterministic_and_scene_isolated():
    items = [
        {"scene": f"scene-{index // 2}", "path": f"{index}.jpg"}
        for index in range(20)
    ]

    first = split_scenes(items, test_scenes=2, validation_scenes=2, seed=42)
    second = split_scenes(items, test_scenes=2, validation_scenes=2, seed=42)

    assert first == second
    assert list(first.values()).count("test") == 2
    assert list(first.values()).count("validation") == 2
    assert list(first.values()).count("train") == 6
