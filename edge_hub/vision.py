from __future__ import annotations

import hashlib
import json
import math
import os
import time
from collections import deque
from dataclasses import dataclass
from importlib.metadata import version
from numbers import Real
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image
from PIL import __version__ as pillow_version

from edge_hub.privacy import blur_boxes, safe_evidence_path

LITTER_CLASSES = ("plastic_bottle", "aluminium_can", "paper_cup", "paper_ball_package")
HOG = cv2.HOGDescriptor((64, 64), (16, 16), (8, 8), (8, 8), 9)
_VISION_SOURCE_SHA256 = hashlib.sha256(
    Path(__file__).read_text(encoding='utf-8').replace('\r\n', '\n').encode('utf-8')
).hexdigest()


def litter_pipeline_identity() -> dict:
    """Loaded component source and dependency compatibility, not a signed acceptance."""
    return {'schema': 'litter-components-v1', 'vision_source_sha256': _VISION_SOURCE_SHA256,
            'opencv_version': cv2.__version__, 'numpy_version': np.__version__,
            'pillow_version': pillow_version,
            'onnxruntime_distribution_version': version('onnxruntime')}


def crop_features(image: np.ndarray) -> np.ndarray:
    resized = cv2.resize(image, (64, 64))
    gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
    hog = HOG.compute(gray).reshape(-1)
    hsv = cv2.cvtColor(resized, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 8], [0, 180, 0, 256]).reshape(-1)
    hist /= max(float(hist.sum()), 1.0)
    return np.concatenate([hog, hist]).astype(np.float32)


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    box: tuple[int, int, int, int]


class TemporalDetectionGate:
    def __init__(self, required_frames: int = 3, confidence_threshold: float = 0.5,
                 rearm_frames: int = 10) -> None:
        self.required_frames = required_frames
        self.confidence_threshold = confidence_threshold
        self.rearm_frames = rearm_frames
        self._tracks: list[dict[str, Any]] = []

    def reset(self) -> None:
        self._tracks.clear()

    def update(self, detections: list[Detection]) -> list[Detection]:
        matched: set[int] = set()
        confirmed = []
        for detection in sorted(detections, key=lambda item: item.confidence, reverse=True):
            if (detection.label not in LITTER_CLASSES or not np.isfinite(detection.confidence)
                    or detection.confidence < self.confidence_threshold):
                continue
            candidates = [(box_iou(track['box'], detection.box), index)
                          for index, track in enumerate(self._tracks) if index not in matched]
            overlap, index = max(candidates, default=(0, -1))
            if overlap < 0.3:
                index = len(self._tracks)
                self._tracks.append({'box': detection.box, 'label': detection.label,
                                     'count': 0, 'missing': 0, 'emitted': False})
            track = self._tracks[index]
            track['count'] = (track['count'] + 1 if track['label'] == detection.label
                              and track['missing'] == 0 else 1)
            track.update(box=detection.box, label=detection.label, missing=0)
            matched.add(index)
            if track['count'] >= self.required_frames and not track['emitted']:
                track['emitted'] = True
                confirmed.append(detection)
        for index, track in enumerate(self._tracks):
            if index not in matched:
                track['missing'] += 1
                track['count'] = 0
        self._tracks = [track for track in self._tracks if track['missing'] < self.rearm_frames]
        return confirmed


def box_iou(first, second) -> float:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    area = max(0, min(ax + aw, bx + bw) - max(ax, bx)) * max(0, min(ay + ah, by + bh) - max(ay, by))
    union = aw * ah + bw * bh - area
    return area / union if union > 0 else 0.0


class EventStormGuard:
    """Bound evidence/event creation; a trip requires explicit operator recalibration."""
    def __init__(self, limit=6, window_seconds=60, clock=time.monotonic):
        self.limit, self.window_seconds, self.clock = limit, window_seconds, clock
        self.timestamps: deque[float] = deque()
        self.tripped = False

    def reset(self):
        self.timestamps.clear()
        self.tripped = False

    def allow(self):
        now = self.clock()
        while self.timestamps and now - self.timestamps[0] >= self.window_seconds:
            self.timestamps.popleft()
        if self.tripped or len(self.timestamps) >= self.limit:
            self.tripped = True
            return False
        self.timestamps.append(now)
        return True


class OnnxObjectDetector:
    """Runs the project ONNX contract: output rows are x1,y1,x2,y2,score,class_id."""

    def __init__(
        self,
        model_path: Path,
        input_size: tuple[int, int] = (320, 320),
        session: Any | None = None,
    ) -> None:
        if session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = int(os.environ.get("ZHIWEI_ONNX_THREADS", "2"))
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        self.session = session
        self.input_name = session.get_inputs()[0].name
        self.input_size = input_size

    def detect(self, image: np.ndarray, threshold: float = 0.5) -> list[Detection]:
        if (isinstance(threshold, bool) or not isinstance(threshold, Real)
                or not math.isfinite(threshold) or not 0 < threshold <= 1):
            raise ValueError('invalid detector threshold')
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
                or image.shape[2] != 3 or min(image.shape[:2]) < 1):
            raise ValueError('invalid detector image: expected nonempty uint8 BGR')
        height, width = image.shape[:2]
        resized = cv2.resize(image, self.input_size)
        tensor = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        tensor = np.transpose(tensor, (2, 0, 1))[None, ...]
        outputs = self.session.run(None, {self.input_name: tensor})
        if not isinstance(outputs, (tuple, list)) or len(outputs) != 1:
            raise ValueError('invalid detector output count')
        rows = np.asarray(outputs[0])
        if rows.ndim == 3 and rows.shape[0] == 1:
            rows = rows[0]
        if (rows.ndim != 2 or rows.shape[1] != 6 or rows.shape[0] > 1000
                or not np.issubdtype(rows.dtype, np.floating) or not np.isfinite(rows).all()):
            raise ValueError('invalid detector output tensor')
        if (np.any(rows[:, 4] < 0) or np.any(rows[:, 4] > 1)
                or np.any(rows[:, 5] != np.floor(rows[:, 5]))
                or np.any(rows[:, 5] < 0) or np.any(rows[:, 5] >= len(LITTER_CLASSES))
                or np.any(rows[:, :4] < 0)
                or np.any(rows[:, [0, 2]] > self.input_size[0])
                or np.any(rows[:, [1, 3]] > self.input_size[1])
                or np.any(rows[:, 2] <= rows[:, 0]) or np.any(rows[:, 3] <= rows[:, 1])):
            raise ValueError('invalid detector score, class or geometry')
        scale_x, scale_y = width / self.input_size[0], height / self.input_size[1]
        detections: list[Detection] = []
        for x1, y1, x2, y2, score, class_id in rows:
            index = int(class_id)
            if score < threshold:
                continue
            box = (round(x1 * scale_x), round(y1 * scale_y),
                   round((x2 - x1) * scale_x), round((y2 - y1) * scale_y))
            if box[2] <= 0 or box[3] <= 0:
                raise ValueError('invalid detector box after pixel scaling')
            detections.append(
                Detection(
                    label=LITTER_CLASSES[index],
                    confidence=float(score),
                    box=box,
                )
            )
        return detections


class PrivacyEvidenceWriter:
    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or Path.cwd()

    def save(
        self,
        image: np.ndarray,
        person_boxes: list[tuple[int, int, int, int]],
        output_path: Path,
        *,
        privacy_check_passed: bool,
    ) -> Path | None:
        if privacy_check_passed is not True:
            return None
        safe_evidence_path(output_path)
        if any(ord(char) < 32 or char in '<>:"|?*' for char in output_path.name):
            raise ValueError('unsafe evidence filename')
        root = self.project_root.resolve()
        destination = root / output_path

        def check_location():
            current = root
            for part in output_path.parts:
                current /= part
                if current.is_symlink() or current.is_junction():
                    raise ValueError('linked evidence path is not permitted')
                if not current.resolve().is_relative_to(root):
                    raise ValueError('evidence destination escapes project root')

        check_location()
        if destination.exists():
            raise FileExistsError('evidence destination already exists')
        blurred = blur_boxes(image, person_boxes)
        encoded_ok, encoded = cv2.imencode('.jpg', blurred)
        if (not encoded_ok or not isinstance(encoded, np.ndarray) or encoded.dtype != np.uint8
                or not 0 < encoded.size <= 8 * 1024**2):
            raise OSError('unable to encode bounded evidence image')
        destination.parent.mkdir(parents=True, exist_ok=True)
        check_location()
        # Exclusive creation also closes the normal concurrent same-name writer race.
        # A partial newly-created blurred file may remain on I/O failure; never delete history.
        with destination.open('xb') as output:
            payload = encoded.tobytes()
            if output.write(payload) != len(payload):
                raise OSError('incomplete evidence write')
        return output_path


class OnnxCropClassifier:
    def __init__(self, model_path: Path, session: Any | None = None) -> None:
        if session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = int(os.environ.get("ZHIWEI_ONNX_THREADS", "2"))
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            session = ort.InferenceSession(
                str(model_path), sess_options=options, providers=["CPUExecutionProvider"]
            )
        self.session = session
        self.input_name = session.get_inputs()[0].name
        self.classes = LITTER_CLASSES
        try:
            encoded_classes = session.get_modelmeta().custom_metadata_map.get('zhiwei_classes')
        except AttributeError:
            encoded_classes = None
        if encoded_classes:
            declared = tuple(json.loads(encoded_classes))
            if declared not in (LITTER_CLASSES, (*LITTER_CLASSES, 'background_unknown')):
                raise ValueError('unsupported classifier classes')
            self.classes = declared
        self.class_weights = np.ones(len(self.classes), dtype=np.float64)
        try:
            metadata = session.get_modelmeta().custom_metadata_map
        except AttributeError:
            metadata = {}
        encoded_weights = metadata.get('zhiwei_class_weights')
        if encoded_weights is not None:
            try:
                declared_weights = json.loads(encoded_weights)
                if (not isinstance(declared_weights, list) or len(declared_weights) != len(self.classes)
                        or any(isinstance(value, bool) or not isinstance(value, Real)
                               or not math.isfinite(value) or value <= 0 for value in declared_weights)):
                    raise ValueError('invalid classifier weights')
                self.class_weights = np.asarray(declared_weights, dtype=np.float64)
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError('invalid classifier weights') from error

    def classify(self, crop: np.ndarray) -> tuple[str, float]:
        probabilities = self.probabilities(crop)
        index = int(probabilities.argmax())
        return self.classes[index], float(probabilities[index])

    def probabilities(self, crop: np.ndarray, *, apply_weights: bool = True) -> np.ndarray:
        if (not isinstance(crop, np.ndarray) or crop.dtype != np.uint8 or crop.ndim != 3
                or crop.shape[2] != 3 or min(crop.shape[:2]) < 1):
            raise ValueError('invalid classifier crop: expected nonempty uint8 BGR')
        input_shape = self.session.get_inputs()[0].shape
        if len(input_shape) == 4:
            input_size = int(input_shape[-1])
            rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            resized = Image.fromarray(rgb).resize(
                (input_size, input_size), Image.Resampling.BILINEAR
            )
            tensor = np.asarray(resized, dtype=np.float32) / 255.0
            tensor = (tensor - np.array([0.485, 0.456, 0.406], dtype=np.float32)) / np.array(
                [0.229, 0.224, 0.225], dtype=np.float32
            )
            model_input = tensor.transpose(2, 0, 1)[None, ...]
        else:
            model_input = crop_features(crop)[None, :]
        outputs = self.session.run(None, {self.input_name: model_input})
        if not isinstance(outputs, (list, tuple)) or not outputs:
            raise ValueError('invalid classifier probabilities output')
        probabilities = np.asarray(outputs[-1])
        if probabilities.shape == (1, len(self.classes)):
            probabilities = probabilities[0]
        if (probabilities.shape != (len(self.classes),)
                or not np.issubdtype(probabilities.dtype, np.floating)
                or not np.isfinite(probabilities).all()
                or np.any(probabilities < 0) or np.any(probabilities > 1)):
            raise ValueError('invalid classifier probabilities')
        probabilities = probabilities.astype(np.float64)
        if apply_weights:
            weights = np.asarray(self.class_weights)
            if (weights.shape != probabilities.shape or not np.issubdtype(weights.dtype, np.floating)
                    or not np.isfinite(weights).all() or np.any(weights <= 0)):
                raise ValueError('invalid classifier weights')
            positive = probabilities > 0
            if not np.any(positive):
                raise ValueError('empty class probabilities')
            log_scores = np.log(probabilities[positive]) + np.log(weights[positive].astype(np.float64))
            probabilities[positive] = np.exp(log_scores - log_scores.max())
        total = float(probabilities.sum())
        if math.isfinite(total) and total > 0:
            probabilities = probabilities / total
        else:
            raise ValueError('empty class probabilities')
        return probabilities


class BackgroundCandidateDetector:
    def __init__(
        self, minimum_area: int = 500, threshold: int = 30, max_candidates: int = 4
    ) -> None:
        self.minimum_area = minimum_area
        self.threshold = threshold
        self.max_candidates = max_candidates
        self._baseline: np.ndarray | None = None
        self.scene_unstable = False
        self.last_diagnostics: dict[str, float | int] = {}

    @staticmethod
    def _gray(frame: np.ndarray) -> np.ndarray:
        return cv2.GaussianBlur(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (7, 7), 0)

    def calibrate(self, clean_frame: np.ndarray) -> None:
        self._baseline = self._gray(clean_frame)
        self.scene_unstable = False

    def candidates(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        if self._baseline is None:
            raise RuntimeError("background detector is not calibrated")
        gray = self._gray(frame)
        if gray.shape != self._baseline.shape:
            raise ValueError("frame size differs from calibration frame")
        # Compensate global exposure changes without learning foreground objects into the baseline.
        delta = gray.astype(np.int16) - self._baseline.astype(np.int16)
        difference = np.clip(np.abs(delta - np.median(delta)), 0, 255).astype(np.uint8)
        mask = cv2.threshold(difference, self.threshold, 255, cv2.THRESH_BINARY)[1]
        changed_fraction = float(np.count_nonzero(mask)) / mask.size
        self.last_diagnostics = {'changed_fraction': round(changed_fraction, 5),
                                 'difference_p95': round(float(np.percentile(difference, 95)), 1),
                                 'exposure_offset': float(np.median(delta))}
        # Ignore the soft Gaussian fringe for the whole-scene movement guard;
        # it must not turn several small valid objects into a scene-change rejection.
        strong_fraction = float(np.count_nonzero(difference > max(self.threshold, 60))) / mask.size
        self.scene_unstable = strong_fraction > 0.3
        if self.scene_unstable:
            return []
        kernel = np.ones((5, 5), dtype=np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(contour) for contour in contours if cv2.contourArea(contour) >= self.minimum_area]
        return sorted(boxes, key=lambda box: box[2] * box[3], reverse=True)[
            : self.max_candidates
        ]


class LitterFrameProcessor:
    def __init__(
        self,
        classifier: OnnxCropClassifier,
        candidate_detector: BackgroundCandidateDetector,
        gate: TemporalDetectionGate | None = None,
    ) -> None:
        self.classifier = classifier
        self.candidate_detector = candidate_detector
        self.gate = gate or TemporalDetectionGate()

    def detect(self, frame: np.ndarray, person_boxes=None) -> list[Detection]:
        return self.gate.update(self.classify_candidates(frame, person_boxes))

    def classify_candidates(self, frame: np.ndarray, person_boxes=None) -> list[Detection]:
        detections: list[Detection] = []
        for x, y, width, height in self.candidate_detector.candidates(frame):
            if any(box_iou((x, y, width, height), person) > 0.1
                   or candidate_covered((x, y, width, height), person) > 0.3
                   for person in (person_boxes or [])):
                continue
            crop = frame[y : y + height, x : x + width]
            label, confidence = self.classifier.classify(crop)
            if label not in LITTER_CLASSES:
                continue
            detections.append(Detection(label, confidence, (x, y, width, height)))
        return detections


def candidate_covered(candidate, person) -> float:
    x, y, w, h = candidate
    px, py, pw, ph = person
    area = max(0, min(x + w, px + pw) - max(x, px)) * max(0, min(y + h, py + ph) - max(y, py))
    return area / (w * h) if w * h > 0 else 0.0
