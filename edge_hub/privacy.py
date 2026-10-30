import hashlib
import math
import os
from importlib.metadata import version
from numbers import Real
from pathlib import Path
from typing import Any

import cv2
import numpy as np

# Capture at import, not each health query after a newer file has been copied over.
_PRIVACY_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')
).hexdigest()


def privacy_face_path(model_path: Path, face_model_path: Path | None = None) -> Path:
    path = face_model_path or model_path.parent / "haarcascade-frontalface-default.xml"
    if not path.is_file():
        path = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
    return path


def privacy_pipeline_identity(model_path: Path, input_size=416, threshold=.15, retain_all=False) -> dict:
    """Read-only compatibility identity, not a signature or proof of correct labels."""
    return {
        'schema': 'privacy-pipeline-v1',
        'privacy_source_sha256': _PRIVACY_SOURCE_SHA256,
        'face_model_sha256': hashlib.sha256(privacy_face_path(model_path).read_bytes()).hexdigest(),
        'opencv_version': cv2.__version__, 'numpy_version': np.__version__,
        'onnxruntime_version': version('onnxruntime'),
        'input_size': input_size, 'confidence_threshold': threshold,
        'person_box_policy': 'all-qualified' if retain_all else 'nms-0.45',
    }


def _yolox_grid(input_size: int) -> tuple[np.ndarray, np.ndarray]:
    grids = []
    expanded_strides = []
    for stride in (8, 16, 32):
        height = width = input_size // stride
        yv, xv = np.meshgrid(np.arange(height), np.arange(width), indexing="ij")
        grid = np.stack((xv, yv), axis=2).reshape(1, -1, 2)
        grids.append(grid)
        expanded_strides.append(np.full((*grid.shape[:2], 1), stride))
    return np.concatenate(grids, axis=1), np.concatenate(expanded_strides, axis=1)


class PersonPrivacyDetector:
    def __init__(
        self,
        model_path: Path,
        input_size: int = 416,
        session: Any | None = None,
        face_model_path: Path | None = None,
        face_cascade: Any | None = None,
        retain_all: bool = False,
    ) -> None:
        if type(retain_all) is not bool:
            raise ValueError('invalid privacy candidate policy')
        self.retain_all = retain_all
        if session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = int(os.environ.get('ZHIWEI_ONNX_THREADS', '2'))
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(model_path), sess_options=options,
                                          providers=["CPUExecutionProvider"])
        self.session = session
        self.input_name = session.get_inputs()[0].name
        self.input_size = input_size
        if face_cascade is None:
            face_path = privacy_face_path(model_path, face_model_path)
            face_cascade = cv2.CascadeClassifier(str(face_path))
            if face_cascade.empty():
                raise FileNotFoundError(f"face privacy model unavailable: {face_path}")
        self.face_cascade = face_cascade

    def _person_boxes(self, image: np.ndarray, threshold: float) -> list[tuple[int, int, int, int]]:
        if (isinstance(threshold, (bool, np.bool_)) or not isinstance(threshold, Real)
                or not math.isfinite(threshold) or not 0 < threshold <= 1):
            raise ValueError("invalid privacy confidence threshold")
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.ndim != 3 or image.shape[2] != 3
                or image.shape[0] <= 0 or image.shape[1] <= 0):
            raise ValueError("invalid privacy image: expected nonempty uint8 BGR")
        height, width = image.shape[:2]
        ratio = min(self.input_size / height, self.input_size / width)
        resized = cv2.resize(image, (round(width * ratio), round(height * ratio)))
        padded = np.full((self.input_size, self.input_size, 3), 114, dtype=np.uint8)
        padded[: resized.shape[0], : resized.shape[1]] = resized
        tensor = padded.transpose(2, 0, 1)[None, ...].astype(np.float32)
        outputs = self.session.run(None, {self.input_name: tensor})
        if not isinstance(outputs, (list, tuple)) or len(outputs) != 1:
            raise ValueError("invalid privacy model output")
        raw = np.array(outputs[0], copy=True)
        grids, strides = _yolox_grid(self.input_size)
        if (raw.shape != (1, grids.shape[1], 85)
                or not np.issubdtype(raw.dtype, np.floating)
                or not np.isfinite(raw).all()
                or np.any(raw[..., 4:] < 0) or np.any(raw[..., 4:] > 1)):
            # Never turn a corrupt/foreign output into a successful empty screen.
            raise ValueError("invalid privacy model output")
        try:
            with np.errstate(over="raise", invalid="raise"):
                raw[..., :2] = (raw[..., :2] + grids) * strides
                raw[..., 2:4] = np.exp(raw[..., 2:4]) * strides
        except FloatingPointError as error:
            raise ValueError("invalid privacy model output geometry") from error
        if not np.isfinite(raw[..., :4]).all() or np.any(raw[..., 2:4] <= 0):
            raise ValueError("invalid privacy model output geometry")
        person_scores = raw[0, :, 4] * raw[0, :, 5]
        selected = np.where(person_scores >= threshold)[0]
        boxes: list[list[int]] = []
        scores: list[float] = []
        for index in selected:
            center_x, center_y, box_width, box_height = raw[0, index, :4]
            x = max(0, round((center_x - box_width / 2) / ratio))
            y = max(0, round((center_y - box_height / 2) / ratio))
            box_width = min(width - x, round(box_width / ratio))
            box_height = min(height - y, round(box_height / ratio))
            if box_width > 0 and box_height > 0:
                boxes.append([x, y, box_width, box_height])
                scores.append(float(person_scores[index]))
        if self.retain_all:
            return [tuple(box) for box in boxes]
        kept = cv2.dnn.NMSBoxes(boxes, scores, threshold, 0.45)
        return [tuple(boxes[int(index)]) for index in np.asarray(kept).reshape(-1)]

    def detect(self, image: np.ndarray, threshold: float = 0.15) -> list[tuple[int, int, int, int]]:
        people = self._person_boxes(image, threshold)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        faces = [tuple(int(value) for value in box) for box in self.face_cascade.detectMultiScale(gray, 1.1, 4)]
        height, width = image.shape[:2]
        padded = []
        for x, y, w, h in [*people, *faces]:
            margin_x, margin_y = max(8, round(w * 0.1)), max(8, round(h * 0.1))
            x1, y1 = max(0, x - margin_x), max(0, y - margin_y)
            x2, y2 = min(width, x + w + margin_x), min(height, y + h + margin_y)
            if x2 > x1 and y2 > y1:
                padded.append((x1, y1, x2 - x1, y2 - y1))
        return padded


def blur_boxes(image: np.ndarray, boxes: list[tuple[int, int, int, int]]) -> np.ndarray:
    result = image.copy()
    for box in boxes:
        if (not isinstance(box, (list, tuple, np.ndarray)) or len(box) != 4
                or any(isinstance(value, (bool, np.bool_))
                       or not isinstance(value, (int, np.integer)) for value in box)):
            raise ValueError("invalid privacy box")
        x, y, width, height = (int(value) for value in box)
        if width <= 0 or height <= 0:
            raise ValueError("invalid privacy box dimensions")
        right, bottom = min(result.shape[1], x + width), min(result.shape[0], y + height)
        x, y = max(0, x), max(0, y)
        width, height = right - x, bottom - y
        if width <= 0 or height <= 0:
            raise ValueError("privacy box does not intersect image")
        roi = result[y:y + height, x:x + width]
        if roi.size:
            tiny = cv2.resize(roi, (max(1, roi.shape[1] // 24), max(1, roi.shape[0] // 24)),
                              interpolation=cv2.INTER_AREA)
            pixelated = cv2.resize(tiny, (roi.shape[1], roi.shape[0]), interpolation=cv2.INTER_NEAREST)
            result[y:y + height, x:x + width] = cv2.GaussianBlur(pixelated, (9, 9), 0)
    return result


def safe_evidence_path(path: Path) -> Path:
    normalized = path.as_posix()
    if (path.is_absolute() or len(path.parts) != 3 or path.parts[:2] != ('data', 'events')
            or not normalized.startswith("data/events/") or not path.name.endswith("-blurred.jpg")):
        raise ValueError("evidence path must contain blurred event output")
    return path
