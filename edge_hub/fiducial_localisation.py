"""Fixed surveyed ArUco anchors, existing JPEGs only. No device/network access.

OpenCV solvePnP supplies camera-relative pose. Metric world pose additionally
requires measured anchor transforms, actual camera calibration and a fixed
base-to-camera mount. This module never authorizes or sends robot movement.
"""
import hashlib
import io
import json
import math
from dataclasses import dataclass
from types import MappingProxyType

import numpy as np
from PIL import Image


def rigid(value):
    matrix = np.asarray(value, dtype=np.float64)
    if (matrix.shape != (4, 4) or not np.isfinite(matrix).all()
            or not np.allclose(matrix[3], [0, 0, 0, 1], atol=1e-8)
            or not np.allclose(matrix[:3, :3].T @ matrix[:3, :3], np.eye(3), atol=1e-5)
            or not math.isclose(np.linalg.det(matrix[:3, :3]), 1, abs_tol=1e-5)
            or np.max(np.abs(matrix[:3, 3])) > 500):
        raise ValueError('invalid_rigid_transform')
    result = matrix.copy()
    result.setflags(write=False)
    return result


@dataclass(frozen=True)
class Calibration:
    width: int
    height: int
    camera: np.ndarray
    distortion: np.ndarray
    base_from_camera: np.ndarray
    anchors: dict
    map_sha256: str
    digest: str

    @classmethod
    def parse(cls, value):
        fields = {'format', 'image_size', 'camera_matrix', 'distortion', 'base_from_camera', 'anchors', 'map_sha256'}
        if type(value) is not dict or set(value) != fields or value['format'] != 'neighbour-aruco-pinhole-v1':
            raise ValueError('explicit_camera_and_anchor_calibration_required')
        if type(value['image_size']) is not list or len(value['image_size']) != 2:
            raise ValueError('invalid_calibration_size')
        width, height = value['image_size']
        if type(width) is not int or type(height) is not int or not 320 <= width <= 1920 or not 240 <= height <= 1080:
            raise ValueError('invalid_calibration_size')
        camera = np.asarray(value['camera_matrix'], dtype=np.float64)
        distortion = np.asarray(value['distortion'], dtype=np.float64)
        if (camera.shape != (3, 3) or not np.isfinite(camera).all()
                or camera[0, 0] <= 0 or camera[1, 1] <= 0
                or not 0 <= camera[0, 2] < width or not 0 <= camera[1, 2] < height
                or camera[0, 1] != 0 or not np.allclose(camera[1:, 0], [0, 0])
                or not np.allclose(camera[2], [0, 0, 1])
                or distortion.shape not in ((4,), (5,), (8,)) or not np.isfinite(distortion).all()
                or np.max(np.abs(distortion)) > 10):
            raise ValueError('invalid_camera_intrinsics')
        identity = value['map_sha256']
        if type(identity) is not str or len(identity) != 64 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('map_digest_required')
        if type(value['anchors']) is not list or not 1 <= len(value['anchors']) <= 50:
            raise ValueError('bounded_surveyed_anchors_required')
        anchors = {}
        for row in value['anchors']:
            if type(row) is not dict or set(row) != {'id', 'size_m', 'world_from_marker'}:
                raise ValueError('invalid_anchor')
            identifier, size = row['id'], row['size_m']
            if (type(identifier) is not int or not 0 <= identifier < 50 or identifier in anchors
                    or type(size) not in (int, float) or not math.isfinite(size) or not .05 <= size <= 1):
                raise ValueError('invalid_anchor_dimensions')
            anchors[identifier] = (float(size), rigid(row['world_from_marker']))
        digest = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        camera.setflags(write=False)
        distortion.setflags(write=False)
        return cls(width, height, camera, distortion, rigid(value['base_from_camera']), MappingProxyType(anchors), identity, digest)


def rotation_distance(a, b):
    return math.acos(float(np.clip((np.trace(a.T @ b)-1)/2, -1, 1)))


class MarkerLocaliser:
    """No guessed FOV/scale, no odometry extrapolation when markers disappear."""
    def __init__(self, calibration):
        import cv2
        self.cv = cv2
        self.calibration = calibration
        self.dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        self.detector = cv2.aruco.ArucoDetector(self.dictionary, parameters)

    def unknown(self, reason, frame_key, captured):
        return {'state': 'unlocated', 'reason': reason, 'frame_key': frame_key,
                'captured_at_ms': captured, 'map_sha256': self.calibration.map_sha256,
                'calibration_sha256': self.calibration.digest, 'motion_authorized': False}

    def estimate(self, jpeg, *, frame_key, captured_at_ms, now_ms, camera_fixed=False):
        config, cv = self.calibration, self.cv
        def unknown(why):
            return self.unknown(why, frame_key, captured_at_ms)

        if type(frame_key) is not str or not 1 <= len(frame_key) <= 128:
            return unknown('frame_identity_required')
        if (type(captured_at_ms) is not int or type(now_ms) is not int
                or not 0 <= now_ms-captured_at_ms <= 500):
            return unknown('frame_stale_or_future')
        if camera_fixed is not True:
            return unknown('fixed_calibrated_camera_mount_required')
        if not isinstance(jpeg, bytes) or not 1 <= len(jpeg) <= 1_500_000:
            return unknown('invalid_image_bound')
        try:
            with Image.open(io.BytesIO(jpeg)) as image:
                if image.format != 'JPEG' or image.size != (config.width, config.height):
                    return unknown('calibrated_image_size_required')
            image = cv.imdecode(np.frombuffer(jpeg, np.uint8), cv.IMREAD_GRAYSCALE)
            if image is None:
                return unknown('invalid_jpeg')
        except (OSError, ValueError, Image.DecompressionBombError):
            return unknown('invalid_jpeg')
        corners, ids, _ = self.detector.detectMarkers(image)
        if ids is None:
            return unknown('no_surveyed_marker_visible')
        identities = [int(i) for i in ids.flatten()]
        if len(identities) != len(set(identities)):
            return unknown('duplicate_marker_identity')
        candidates = []
        for identifier, points in zip(identities, corners):
            if identifier not in config.anchors:
                continue
            size, world_from_marker = config.anchors[identifier]
            image_points = np.asarray(points, np.float64).reshape(4, 2)
            if abs(cv.contourArea(image_points.astype(np.float32))) < 400:
                continue
            half = size/2
            object_points = np.array([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]], np.float64)
            result = cv.solvePnPGeneric(object_points, image_points, config.camera, config.distortion, flags=cv.SOLVEPNP_IPPE_SQUARE)
            solutions = []
            for rvec, tvec in zip(result[1], result[2]):
                rotation = cv.Rodrigues(rvec)[0]
                if not np.isfinite(rotation).all() or not np.isfinite(tvec).all():
                    continue
                if np.min((rotation @ object_points.T + tvec).T[:, 2]) <= .05:
                    continue
                projected = cv.projectPoints(object_points, rvec, tvec, config.camera, config.distortion)[0].reshape(4, 2)
                error = float(np.sqrt(np.mean(np.sum((projected-image_points)**2, axis=1))))
                if not math.isfinite(error) or error > 1.5:
                    continue
                camera_from_marker = np.eye(4)
                camera_from_marker[:3, :3], camera_from_marker[:3, 3] = rotation, tvec.flatten()
                world_from_base = world_from_marker @ np.linalg.inv(camera_from_marker) @ np.linalg.inv(config.base_from_camera)
                if (abs(world_from_base[2, 3]) > .15
                        or world_from_base[2, 2] < math.cos(math.radians(10))):
                    continue
                solutions.append((error, world_from_base))
            solutions.sort(key=lambda row: row[0])
            if not solutions:
                continue
            error, pose = solutions[0]
            if len(solutions) > 1:
                second_error, second = solutions[1]
                if second_error < max(.4, error*2) and (np.linalg.norm(second[:3, 3]-pose[:3, 3]) > .1
                        or rotation_distance(second[:3, :3], pose[:3, :3]) > math.radians(10)):
                    continue
            candidates.append((identifier, error, pose))
        if not candidates:
            return unknown('marker_pose_rejected_or_ambiguous')
        candidates.sort(key=lambda row: row[1])
        reference = candidates[0][2]
        if any(np.linalg.norm(pose[:3, 3]-reference[:3, 3]) > .15
               or rotation_distance(pose[:3, :3], reference[:3, :3]) > math.radians(10) for _, _, pose in candidates):
            return unknown('surveyed_markers_disagree')
        # Keep the lowest-error physical estimate, rather than fabricating an
        # averaged orientation or silently accepting inconsistent anchors.
        return {'state': 'located', 'x_m': float(reference[0, 3]), 'y_m': float(reference[1, 3]),
                'yaw_rad': math.atan2(reference[1, 0], reference[0, 0]),
                'reprojection_px': candidates[0][1], 'marker_ids': [row[0] for row in candidates],
                'captured_at_ms': captured_at_ms, 'frame_key': frame_key,
                'map_sha256': config.map_sha256, 'calibration_sha256': config.digest,
                'motion_authorized': False}
