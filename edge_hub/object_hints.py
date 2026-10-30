"""Small existing YOLOX ONNX object hints; not a water/fire/electricity detector.

Uses the existing locally verified weights, not a replacement privacy model.
Every result still requires scene interpretation and staff confirmation.
"""
import threading
from pathlib import Path

import cv2
import numpy as np

from edge_hub.privacy import _yolox_grid

LABELS = {0:'person',24:'backpack',26:'handbag',28:'suitcase',39:'bottle',40:'wine glass',41:'cup',
          42:'fork',43:'knife',44:'spoon',45:'bowl',46:'banana',47:'apple',49:'orange',
          56:'chair',57:'couch',58:'potted plant',59:'bed',60:'dining table',62:'tv',
          63:'laptop',65:'remote',66:'keyboard',67:'cell phone',68:'microwave',69:'oven',
          70:'toaster',71:'sink',72:'refrigerator',73:'book',74:'clock',75:'vase',76:'scissors'}


class ObjectHints:
    def __init__(self, path, session=None):
        if session is None:
            import onnxruntime as ort
            options=ort.SessionOptions()
            options.intra_op_num_threads=2
            options.inter_op_num_threads=1
            session=ort.InferenceSession(str(path),sess_options=options,providers=['CPUExecutionProvider'])
        self.session=session
        self.name=session.get_inputs()[0].name
        self.lock=threading.Lock()

    def detect(self, image):
        height,width=image.shape[:2]
        ratio=min(416/height,416/width)
        resized=cv2.resize(image,(round(width*ratio),round(height*ratio)))
        padded=np.full((416,416,3),114,dtype=np.uint8)
        padded[:resized.shape[0],:resized.shape[1]]=resized
        with self.lock:
            raw=np.array(self.session.run(None,{self.name:padded.transpose(2,0,1)[None].astype(np.float32)})[0],copy=True)
        grids,_strides=_yolox_grid(416)
        if raw.shape != (1,grids.shape[1],85) or not np.isfinite(raw).all() or np.any(raw[...,4:] < 0) or np.any(raw[...,4:] > 1):
            raise ValueError('invalid_object_output')
        # Count only one class occurrence per frame; duplicate boxes cannot
        # inflate a candidate count and no identity/intent is inferred.
        scores=raw[0,:,4,None]*raw[0,:,5:]
        winners=scores.argmax(axis=1)
        return sorted({LABELS[int(cls)] for idx,cls in enumerate(winners)
                       if int(cls) in LABELS and scores[idx,cls]>=.5})[:20]


_detector=None
_lock=threading.Lock()


def object_hints(image):
    global _detector
    path=Path(__file__).resolve().parents[1]/'models/person-yolox-tiny.onnx'
    if not path.is_file():
        return []
    with _lock:
        if _detector is None:
            _detector=ObjectHints(path)
    return _detector.detect(image)
