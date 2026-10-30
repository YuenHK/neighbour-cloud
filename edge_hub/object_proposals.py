"""Generic COCO bottle/cup proposals for offline research, NOT litter classifications."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from edge_hub.privacy import _yolox_grid


@dataclass(frozen=True)
class GenericProposal:
    kind: str
    confidence: float
    box: tuple[int, int, int, int]


class GenericYoloxProposals:
    def __init__(self, model_path: Path | None, *, input_size=416, session=None):
        if input_size <= 0 or input_size % 32:
            raise ValueError('YOLOX input size must be a positive multiple of 32')
        if session is None:
            import onnxruntime as ort

            options = ort.SessionOptions()
            options.intra_op_num_threads = 2
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(model_path), sess_options=options, providers=['CPUExecutionProvider'])
        self.session, self.input_size = session, input_size
        entry = session.get_inputs()[0]
        if list(entry.shape) != [1, 3, input_size, input_size]:
            raise ValueError('model input shape does not match proposal contract')
        self.input_name = entry.name
        self.grids, self.strides = _yolox_grid(input_size)

    def detect(self, image, threshold=.3):
        if not 0 < threshold < 1 or image.ndim != 3 or image.shape[2] != 3 or not image.size:
            raise ValueError('invalid image or proposal threshold')
        height, width = image.shape[:2]
        ratio = min(self.input_size / height, self.input_size / width)
        resized = cv2.resize(image, (max(1, int(width * ratio)), max(1, int(height * ratio))))
        padded = np.full((self.input_size, self.input_size, 3), 114, np.uint8)
        padded[:resized.shape[0], :resized.shape[1]] = resized
        tensor = padded.transpose(2, 0, 1)[None].astype(np.float32)
        raw = np.asarray(self.session.run(None, {self.input_name: tensor})[0]).copy()
        if (raw.shape != (1, self.grids.shape[1], 85) or not np.isfinite(raw).all()
                or np.any(raw[..., 4:] < 0) or np.any(raw[..., 4:] > 1)):
            raise ValueError('unsupported YOLOX output shape/probabilities')
        raw[..., :2] = (raw[..., :2] + self.grids) * self.strides
        raw[..., 2:4] = np.exp(np.clip(raw[..., 2:4], -20, 20)) * self.strides
        proposals = []
        # COCO classes 39 and 41 are generic bottle and cup, not material or discarded-state labels.
        for index, name in [(39, 'bottle'), (41, 'cup')]:
            scores = raw[0, :, 4] * raw[0, :, 5 + index]
            boxes, confidences = [], []
            for row in np.where(scores >= threshold)[0]:
                cx, cy, w, h = raw[0, row, :4] / ratio
                x1, y1 = max(0, round(cx - w / 2)), max(0, round(cy - h / 2))
                x2, y2 = min(width, round(cx + w / 2)), min(height, round(cy + h / 2))
                if x2 > x1 and y2 > y1:
                    boxes.append([x1, y1, x2 - x1, y2 - y1])
                    confidences.append(float(scores[row]))
            if boxes:
                kept = cv2.dnn.NMSBoxes(boxes, confidences, threshold, .45)
                for row in np.asarray(kept).reshape(-1):
                    proposals.append(GenericProposal('coco:' + name, confidences[int(row)], tuple(boxes[int(row)])))
        return sorted(proposals, key=lambda item: item.confidence, reverse=True)
