"""Joint surveyed-marker pose from saved JPEGs; no camera, network or actuator.

All visible surveyed marker corners share one physical camera pose. Planar
layouts use IPPE's multiple solutions; non-planar layouts use SQPnP. A second
marker is not automatically evidence of an unambiguous or well-conditioned pose.
"""
import io
import math

import numpy as np
from PIL import Image

from edge_hub.fiducial_localisation import MarkerLocaliser, rotation_distance


def world_corners(calibration, identifier):
    size, transform = calibration.anchors[identifier]
    half = size / 2
    corners = np.array([[-half, half, 0, 1], [half, half, 0, 1],
                        [half, -half, 0, 1], [-half, -half, 0, 1]], np.float64)
    return (transform @ corners.T).T[:, :3]


class BoardLocaliser(MarkerLocaliser):
    """At least two calibrated anchors, all-or-nothing geometry agreement.

    This deliberately has no single-marker fallback or odometry extrapolation.
    A caller may explicitly retain the old single-marker mode separately.
    """

    def estimate(self, jpeg, *, frame_key, captured_at_ms, now_ms, camera_fixed=False):
        config, cv = self.calibration, self.cv

        def reject(reason):
            return self.unknown(reason, frame_key, captured_at_ms)

        if type(frame_key) is not str or not 1 <= len(frame_key) <= 128:
            return reject('frame_identity_required')
        if (type(captured_at_ms) is not int or type(now_ms) is not int
                or not 0 <= now_ms-captured_at_ms <= 500):
            return reject('frame_stale_or_future')
        if camera_fixed is not True:
            return reject('fixed_calibrated_camera_mount_required')
        if type(jpeg) is not bytes or not 1 <= len(jpeg) <= 1_500_000:
            return reject('invalid_image_bound')
        try:
            with Image.open(io.BytesIO(jpeg)) as header:
                if header.format != 'JPEG' or header.size != (config.width, config.height):
                    return reject('calibrated_image_size_required')
            image = cv.imdecode(np.frombuffer(jpeg, np.uint8), cv.IMREAD_GRAYSCALE)
            if image is None:
                return reject('invalid_jpeg')
        except (OSError, ValueError, Image.DecompressionBombError):
            return reject('invalid_jpeg')
        corners, ids, _ = self.detector.detectMarkers(image)
        if ids is None:
            return reject('two_surveyed_markers_required')
        identities = [int(i) for i in ids.flatten()]
        if len(set(identities)) != len(identities):
            return reject('duplicate_marker_identity')
        observations = []
        for identifier, points in zip(identities, corners):
            if identifier not in config.anchors:
                continue
            pixels = np.asarray(points, np.float64).reshape(4, 2)
            # A decoded but tiny/cropped known marker cannot be silently dropped
            # to make another candidate pass the joint geometry checks.
            if (not np.isfinite(pixels).all() or abs(cv.contourArea(pixels.astype(np.float32))) < 400
                    or pixels[:, 0].min() < 3 or pixels[:, 1].min() < 3
                    or pixels[:, 0].max() > config.width-4 or pixels[:, 1].max() > config.height-4):
                return reject('marker_pixels_not_well_observed')
            observations.append((identifier, world_corners(config, identifier), pixels))
        if not 2 <= len(observations) <= 12:
            return reject('two_to_twelve_surveyed_markers_required')
        observations.sort(key=lambda row: row[0])
        object_points = np.concatenate([row[1] for row in observations])
        image_points = np.concatenate([row[2] for row in observations])
        world_centres = np.array([row[1].mean(axis=0) for row in observations])
        image_centres = np.array([row[2].mean(axis=0) for row in observations])
        world_baseline = max(np.linalg.norm(a-b) for a in world_centres for b in world_centres)
        pixel_baseline = max(np.linalg.norm(a-b) for a in image_centres for b in image_centres)
        if world_baseline < .2 or pixel_baseline < 45:
            return reject('insufficient_marker_baseline')
        centred = object_points-object_points.mean(axis=0)
        singular = np.linalg.svd(centred, compute_uv=False)
        if singular[1] < .1 or singular[1]/singular[0] < .08:
            return reject('degenerate_anchor_distribution')
        planar = singular[2]/singular[0] < 1e-6
        method = cv.SOLVEPNP_IPPE if planar else cv.SOLVEPNP_SQPNP
        try:
            result = cv.solvePnPGeneric(object_points, image_points, config.camera, config.distortion, flags=method)
        except cv.error:
            return reject('joint_pose_solver_rejected')
        solutions = []
        for raw_rotation, raw_translation in zip(result[1], result[2]):
            if not np.isfinite(raw_rotation).all() or not np.isfinite(raw_translation).all():
                continue
            candidates = [(raw_rotation, raw_translation)]
            try:
                candidates.append(cv.solvePnPRefineLM(object_points, image_points, config.camera,
                    config.distortion, raw_rotation.copy(), raw_translation.copy()))
            except (cv.error, ValueError, np.linalg.LinAlgError):
                pass
            # Keep raw physically plausible branches even if LM converges both
            # seeds to the same minimum. Refinement must not erase ambiguity.
            for rotation, translation in candidates:
                candidate = self._evaluate(object_points, image_points, rotation, translation)
                if candidate is not None:
                    solutions.append(candidate)
        solutions.sort(key=lambda row: row[0])
        if not solutions:
            return reject('joint_pose_rejected_or_poorly_observable')
        error, pose, sigma, yaw_sigma = solutions[0]
        if any(second_error < max(.4, 2*error)
               and (np.linalg.norm(second[:3, 3]-pose[:3, 3]) > .05
                    or rotation_distance(second[:3, :3], pose[:3, :3]) > math.radians(3))
               for second_error, second, _, _ in solutions[1:]):
            return reject('joint_pose_ambiguous')
        return {'state': 'located', 'x_m': float(pose[0, 3]), 'y_m': float(pose[1, 3]),
            'yaw_rad': math.atan2(pose[1, 0], pose[0, 0]), 'reprojection_px': error,
            'marker_ids': [row[0] for row in observations], 'captured_at_ms': captured_at_ms,
            'frame_key': frame_key, 'map_sha256': config.map_sha256,
            'calibration_sha256': config.digest, 'motion_authorized': False,
            'method': 'joint_planar_ippe' if planar else 'joint_nonplanar_sqpnp',
            'world_baseline_m': float(world_baseline), 'pixel_baseline': float(pixel_baseline),
            'linearised_pixel_noise_position_sigma_m': sigma,
            'linearised_pixel_noise_yaw_sigma_rad': yaw_sigma,
            'is_real_world_accuracy_guarantee': False}

    def _evaluate(self, object_points, image_points, rotation, translation):
        cv, config = self.cv, self.calibration
        try:
            world_from_base = self._world_from_base(rotation, translation)
            camera_rotation = cv.Rodrigues(rotation)[0]
            if np.min((camera_rotation @ object_points.T + translation).T[:, 2]) <= .05:
                return None
            if (abs(world_from_base[2, 3]) > .15
                    or world_from_base[2, 2] < math.cos(math.radians(10))):
                return None
            projected, jacobian = cv.projectPoints(object_points, rotation, translation, config.camera, config.distortion)
            residual = np.linalg.norm(projected.reshape(-1, 2)-image_points, axis=1)
            per_marker = np.sqrt(np.mean(residual.reshape(-1, 4)**2, axis=1))
            rms = float(np.sqrt(np.mean(residual**2)))
            if not math.isfinite(rms) or rms > 1.5 or np.max(per_marker) > 1.5 or np.max(residual) > 3:
                return None
            # Local pixel-noise sensitivity excludes systematic calibration and
            # survey error. It is an observability fence, not confidence proof.
            sigma, yaw_sigma = self._sensitivity(rotation, translation, jacobian[:, :6], max(.5, rms))
            if sigma > .05 or yaw_sigma > math.radians(3):
                return None
            return rms, world_from_base, sigma, yaw_sigma
        except (cv.error, ValueError, np.linalg.LinAlgError):
            return None

    def _world_from_base(self, rotation, translation):
        camera_from_world = np.eye(4)
        camera_from_world[:3, :3] = self.cv.Rodrigues(rotation)[0]
        camera_from_world[:3, 3] = translation.flatten()
        return np.linalg.inv(camera_from_world) @ np.linalg.inv(self.calibration.base_from_camera)

    def _sensitivity(self, rotation, translation, jacobian, pixel_sigma):
        _, singular, vectors = np.linalg.svd(jacobian, full_matrices=False)
        if len(singular) != 6 or singular[-1] <= 1e-8 or singular[0]/singular[-1] > 1e7:
            raise ValueError('pose_jacobian_ill_conditioned')
        covariance = (vectors.T @ np.diag(1/singular**2) @ vectors) * pixel_sigma**2
        params = np.concatenate([rotation.flatten(), translation.flatten()])

        def planar_pose(value):
            pose = self._world_from_base(value[:3].reshape(3, 1), value[3:].reshape(3, 1))
            return np.array([pose[0, 3], pose[1, 3], math.atan2(pose[1, 0], pose[0, 0])])

        sensitivity = np.zeros((3, 6))
        for index in range(6):
            delta = np.zeros(6)
            delta[index] = 1e-6
            difference = planar_pose(params+delta)-planar_pose(params-delta)
            difference[2] = (difference[2]+math.pi) % (2*math.pi)-math.pi
            sensitivity[:, index] = difference/2e-6
        planar_covariance = sensitivity @ covariance @ sensitivity.T
        sigma = math.sqrt(max(0., float(np.linalg.eigvalsh(planar_covariance[:2, :2]).max())))
        yaw_sigma = math.sqrt(max(0., float(planar_covariance[2, 2])))
        if not math.isfinite(sigma) or not math.isfinite(yaw_sigma):
            raise ValueError('pose_sensitivity_invalid')
        return sigma, yaw_sigma
