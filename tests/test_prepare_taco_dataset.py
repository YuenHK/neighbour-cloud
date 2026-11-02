import json
from pathlib import Path

import cv2
import numpy as np

from tools.prepare_taco_dataset import prepare_taco


def test_taco_mapping_crops_only_approved_classes(tmp_path: Path) -> None:
    image_root = tmp_path / "source"
    image_path = image_root / "batch_1" / "image.jpg"
    image_path.parent.mkdir(parents=True)
    cv2.imwrite(str(image_path), np.full((50, 50, 3), 127, dtype=np.uint8))
    annotations = {
        "images": [{"id": 1, "file_name": "batch_1/image.jpg", "width": 50, "height": 50}],
        "categories": [{"id": 1, "name": "Paper cup"}, {"id": 2, "name": "Shoe"}],
        "annotations": [
            {"id": 10, "image_id": 1, "category_id": 1, "bbox": [5, 5, 20, 20]},
            {"id": 11, "image_id": 1, "category_id": 2, "bbox": [5, 5, 20, 20]},
        ],
    }
    annotation_path = tmp_path / "annotations.json"
    annotation_path.write_text(json.dumps(annotations), encoding="utf-8")

    result = prepare_taco(annotation_path, image_root, tmp_path / "prepared")

    assert result["original_counts"] == {"paper_cup": 1}
    assert len(result["items"]) == 1
    assert result["items"][0]["source_class"] == "Paper cup"
    assert (tmp_path / "prepared" / result["items"][0]["path"]).is_file()
