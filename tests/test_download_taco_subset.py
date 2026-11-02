import json
from pathlib import Path

from tools.download_taco_subset import required_images


def test_download_subset_selects_only_mapped_classes(tmp_path: Path) -> None:
    data = {
        "images": [{"id": 1}, {"id": 2}],
        "categories": [{"id": 1, "name": "Drink can"}, {"id": 2, "name": "Shoe"}],
        "annotations": [
            {"image_id": 1, "category_id": 1},
            {"image_id": 2, "category_id": 2},
        ],
    }
    path = tmp_path / "annotations.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    assert required_images(path) == [{"id": 1}]
