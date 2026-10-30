from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path

import cv2

from edge_hub.event_request import check_event_json_depth
from edge_hub.events import Event, EventStore
from edge_hub.privacy import PersonPrivacyDetector, privacy_pipeline_identity
from edge_hub.vision import (
    LITTER_CLASSES,
    BackgroundCandidateDetector,
    EventStormGuard,
    LitterFrameProcessor,
    OnnxCropClassifier,
    PrivacyEvidenceWriter,
    litter_pipeline_identity,
)


def vision_opt_in(value: str) -> bool:
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def vision_frame_interval(value: str) -> float:
    try:
        seconds = float(value) / 1000
    except (ValueError, OverflowError):
        raise ValueError('invalid vision polling interval') from None
    if not math.isfinite(seconds) or not 0 < seconds <= threading.TIMEOUT_MAX:
        raise ValueError('invalid vision polling interval')
    return seconds


def configured_vision_enabled(marker: Path) -> bool:
    try:
        return vision_opt_in(marker.read_text(encoding='ascii'))
    except FileNotFoundError:
        return vision_opt_in(os.environ.get('ZHIWEI_VISION_ENABLED', 'false'))
    except (OSError, UnicodeError):
        return False


def score_in_range(value, minimum):
    # Compare bounds before float conversion: JSON integers may exceed float capacity.
    return (type(value) in (int, float) and minimum <= value <= 1. and math.isfinite(value))


def _report_members(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('ambiguous model report')
        result[key] = value
    return result


def _report_constant(value):
    raise ValueError('nonstandard model report')


def _report_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError('nonfinite model report')
    return result


def _read_model_report(path):
    with path.open('rb') as source:
        raw = source.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError('model report exceeds size limit')
    check_event_json_depth(raw, max_depth=64)
    report = json.loads(raw, object_pairs_hook=_report_members,
                        parse_constant=_report_constant, parse_float=_report_float)
    if not isinstance(report, dict):
        raise TypeError('model report must be an object')
    return report


class VisionRuntime:
    def __init__(
        self, project_root: Path, store: EventStore, *, enabled: bool | None = None
    ) -> None:
        self.project_root = project_root
        self.store = store
        self.enabled = (
            enabled is True
            if enabled is not None
            else vision_opt_in(os.environ.get('ZHIWEI_VISION_ENABLED', 'false'))
        )
        self.litter_model = Path(
            os.environ.get("ZHIWEI_VISION_MODEL", project_root / "models/litter-classifier.onnx")
        )
        self.person_model = Path(
            os.environ.get("ZHIWEI_PERSON_MODEL", project_root / "models/person-yolox-tiny.onnx")
        )
        self.model_report = self.litter_model.with_suffix(".report.json")
        self.camera_index = int(os.environ.get("ZHIWEI_CAMERA_INDEX", "0"))
        self.zone = os.environ.get("ZHIWEI_CAMERA_ZONE", "A1")
        self.frame_interval = vision_frame_interval(os.environ.get("ZHIWEI_VISION_INTERVAL_MS", "300"))
        self._stop = threading.Event()
        self._calibrate = threading.Event()
        self._lifecycle_lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._status = "stopped"
        self._error: str | None = None
        self._frames = 0
        self._events = 0
        self._storm_trips = 0
        self._last_frame_tick: float | None = None

    def status(self) -> dict[str, object]:
        model_accepted = self._model_accepted()
        last_frame_tick = self._last_frame_tick
        frame_age = (None if last_frame_tick is None
                     else round(max(0., time.monotonic() - last_frame_tick) * 1000, 3))
        worker_alive = bool(self._thread and self._thread.is_alive())
        state = self._status
        if self._stop.is_set() and worker_alive:
            state = 'stopping'
        elif self._stop.is_set() and state not in {
                'failed', 'stopped', 'disabled', 'camera_unavailable', 'privacy_unavailable'}:
            # A delayed worker may have published a nonterminal phase after join timed out.
            state = 'stopped' if self.enabled else 'disabled'
        return {
            "status": state,
            "enabled": self.enabled,
            "worker_alive": worker_alive,
            "stop_requested": self._stop.is_set(),
            "error": self._error,
            "camera_index": self.camera_index,
            "zone": self.zone,
            "frames_processed": self._frames,
            "events_created": self._events,
            "event_storm_trips": self._storm_trips,
            "last_frame_age_ms": frame_age,
            "poll_interval_ms": self.frame_interval * 1000,
            "frame_observation_scope": 'successful read return only; not image quality, inference or hardware proof',
            "litter_model_ready": self.litter_model.is_file(),
            "litter_model_accepted": model_accepted,
            "person_model_ready": self.person_model.is_file(),
            "person_privacy_accepted": self._privacy_accepted(),
            "acceptance_rule": 'each_class_precision_recall_80_and_person_coverage_95',
            "raw_frames_saved": 0,
        }

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            if not self.enabled:
                self._status = "disabled"
                return
            if not self._model_accepted() or not self.person_model.is_file() or not self._privacy_accepted():
                self._status = "waiting_for_models"
                return
            self._stop.clear()
            self._status = 'starting'
            self._error = None
            self._last_frame_tick = None
            try:
                self._thread = threading.Thread(target=self._run, name="litter-vision", daemon=True)
                self._thread.start()
            except Exception:  # noqa: BLE001 - redact launch boundary errors in public status.
                self._stop.set()
                self._status = 'failed'
                self._error = 'vision worker start failed'
                # Thread.start failure normally leaves an unstarted, unjoinable handle.
                # Retain an unexpectedly live handle so a retry cannot duplicate it.
                if self._thread and not self._thread.is_alive():
                    self._thread = None

    def _model_accepted(self) -> bool:
        if not self.litter_model.is_file() or not self.model_report.is_file():
            return False
        try:
            report = _read_model_report(self.model_report)
            classes = report['metrics']['classes']
            balanced = report['balanced_acceptance']
            counts = balanced['sample_counts']
            return (report.get('evaluation_role') == 'public-regression'
                    and report.get('formal_evaluation_eligible') is True
                    and report.get('evaluation_scope') == 'scene-events-with-background'
                    and report.get('pipeline_identity') == litter_pipeline_identity()
                    and report.get('model_sha256') == hashlib.sha256(self.litter_model.read_bytes()).hexdigest()
                    and balanced.get('passed') is True
                    and set(classes) == set(LITTER_CLASSES)
                    and set(counts) == set(LITTER_CLASSES)
                    and all(type(count) is int and count >= 20 for count in counts.values())
                    and all(score_in_range(values['precision'], .8) and score_in_range(values['recall'], .8)
                            for values in classes.values()))
        except (OSError, KeyError, TypeError, ValueError, AttributeError, ImportError, RecursionError):
            return False

    def _privacy_accepted(self) -> bool:
        report_path = self.person_model.parent / 'person-privacy.report.json'
        try:
            report = _read_model_report(report_path)
            return (report.get('masking_protocol') == 'all-human-coverage-95-v3'
                    and report.get('evaluation_role') == 'public-regression'
                    and report.get('production_gate_eligible') is True
                    and report.get('ground_truth_scope') == 'all_annotated_human_boxes'
                    and report.get('annotation_audit', {}).get('human_label_coverage_verified') is True
                    and report.get('annotation_audit', {}).get('unscored_unique_human_boxes') == 0
                    and report.get('mask_coverage_required') == 0.95
                    and report.get('pipeline_identity') == privacy_pipeline_identity(self.person_model)
                    and report.get('inference_layout') == 'full-frame'
                    and report.get('inference_calls_per_image') == 1
                    and type(report.get('evaluated')) is int and report['evaluated'] >= 100
                    and score_in_range(report.get('pass_rate'), .95)
                    and report.get('passed') is True
                    and report.get('model_sha256') == hashlib.sha256(self.person_model.read_bytes()).hexdigest())
        except (OSError, ValueError, TypeError, AttributeError, ImportError, RecursionError):
            return False

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            if self._thread and self._thread is not threading.current_thread():
                self._thread.join(timeout=3)
            if self._thread and self._thread.is_alive():
                self._status = 'stopping'
            elif self._status != 'failed':
                self._status = "stopped"

    def disable(self) -> None:
        with self._lifecycle_lock:
            self.enabled = False
            self.stop()
            if not (self._thread and self._thread.is_alive()) and self._status != 'failed':
                self._status = "disabled"

    def enable(self) -> None:
        with self._lifecycle_lock:
            self.enabled = True
            self.start()

    def request_calibration(self) -> None:
        self._calibrate.set()

    def _run(self) -> None:
        if self._stop.is_set():
            return  # A delayed scheduled worker must not open a device after stop.
        camera = None
        phase = 'camera'
        self._error = None
        try:
            camera = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
            if not camera.isOpened():
                self._status = "camera_unavailable"
                self._error = 'camera unavailable'
                return
            if self._stop.is_set():
                return
            phase = 'pipeline'
            classifier = OnnxCropClassifier(self.litter_model)
            if self._stop.is_set():
                return
            privacy = PersonPrivacyDetector(self.person_model)
            if self._stop.is_set():
                return
            candidates = BackgroundCandidateDetector()
            processor = LitterFrameProcessor(classifier, candidates)
            writer = PrivacyEvidenceWriter(self.project_root)
            storm_guard = EventStormGuard()
            calibrated = False
            self._status = "starting"
            while not self._stop.is_set():
                ok, frame = camera.read()
                if self._stop.is_set():
                    break
                if not ok:
                    self._error = "camera frame unavailable"
                    self._stop.wait(0.2)
                    continue
                self._last_frame_tick = time.monotonic()
                if not calibrated and not self._calibrate.is_set():
                    self._status = 'waiting_for_clean_scene_calibration'
                    self._stop.wait(self.frame_interval)
                    continue
                if self._calibrate.is_set():
                    candidates.calibrate(frame)
                    if self._stop.is_set():
                        break
                    processor.gate.reset()
                    storm_guard.reset()
                    self._calibrate.clear()
                    calibrated = True
                    self._status = "running"
                    self._stop.wait(0.25)
                    continue
                if storm_guard.tripped:
                    self._status = 'paused_event_storm_recalibration_required'
                    self._stop.wait(self.frame_interval)
                    continue
                self._frames += 1
                candidate_boxes = candidates.candidates(frame)
                if self._stop.is_set():
                    break
                if not candidate_boxes:
                    processor.gate.update([])
                    self._status = 'scene_unstable' if candidates.scene_unstable else 'running'
                    self._stop.wait(self.frame_interval)
                    continue
                try:
                    person_boxes = privacy.detect(frame)
                except Exception:  # noqa: BLE001 - never classify people without privacy screening
                    processor.gate.update([])
                    self._error = 'privacy detector failed'
                    self._status = 'privacy_unavailable'
                    self._stop.wait(self.frame_interval)
                    continue
                if self._stop.is_set():
                    break
                detections = processor.detect(frame, person_boxes)
                if self._stop.is_set():
                    break
                self._error = None
                self._status = 'scene_unstable' if candidates.scene_unstable else 'running'
                for detection in detections:
                    if self._stop.is_set():
                        break
                    if not storm_guard.allow():
                        self._storm_trips += 1
                        self._status = 'paused_event_storm_recalibration_required'
                        break
                    event_id = f"evt-litter-{uuid.uuid4().hex}"
                    relative_path = Path("data/events") / f"{event_id}-blurred.jpg"
                    saved = writer.save(
                        frame,
                        person_boxes,
                        relative_path,
                        privacy_check_passed=True,
                    )
                    if self._stop.is_set():
                        break
                    event = Event(
                        id=event_id,
                        type="litter_detected",
                        zone=self.zone,
                        at_ms=int(time.time() * 1000),
                        severity="notice",
                        evidence=saved.relative_to("data").as_posix() if saved else None,
                        details={
                            "label": detection.label,
                            "confidence": round(detection.confidence, 4),
                            "privacy": "blurred" if saved else "text_only",
                        },
                    )
                    self.store.add(event)
                    self._events += 1
                self._stop.wait(self.frame_interval)
        except Exception:  # noqa: BLE001 - only fixed messages may reach public status
            self._status = "failed"
            self._error = 'camera initialization failed' if phase == 'camera' else 'vision pipeline failed'
        finally:
            if camera is not None:
                try:
                    camera.release()
                except Exception:  # noqa: BLE001 - do not leak release exceptions from the worker
                    self._status = 'failed'
                    self._error = 'camera release failed'
