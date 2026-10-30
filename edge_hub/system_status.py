from __future__ import annotations

import os
from pathlib import Path

from edge_hub.cloud_credentials import siliconflow_enabled


def local_system_status(project_root: Path, *, robot_status=None) -> dict[str, object]:
    model_path = Path(
        os.environ.get("ZHIWEI_VISION_MODEL", project_root / "models/litter-classifier.onnx")
    )
    return {
        'conversation_processing': 'siliconflow-free' if siliconflow_enabled() else 'local',
        'speech_synthesis': 'local',
        "vision_model": {
            "configured": model_path.is_file(),
            "filename": model_path.name,
            "mode": "local-onnx",
        },
        "camera_processing": "local-only",
        "raw_image_persistence": "forbidden",
        "robot_transport": robot_status['mode'] if robot_status else 'simulation',
        "robot_connected": bool(robot_status and robot_status['connected']),
        "hardware_acceptance": False,
    }
