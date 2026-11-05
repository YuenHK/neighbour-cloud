"""Calibrated metric replay, never opens a camera or robot connection."""
import copy
import math

import cv2
import numpy as np
import pytest

from edge_hub.fiducial_localisation import Calibration, MarkerLocaliser


def fixture():
    return {
        'format': 'neighbour-aruco-pinhole-v1', 'image_size': [640, 360],
        'camera_matrix': [[600, 0, 320], [0, 600, 180], [0, 0, 1]],
        'distortion': [0, 0, 0, 0, 0],
        'base_from_camera': [[0, 0, 1, .05], [-1, 0, 0, 0], [0, -1, 0, .25], [0, 0, 0, 1]],
        'anchors': [{'id': 7, 'size_m': .4,
                     'world_from_marker': [[0, 0, -1, 2.5], [-1, 0, 0, 0], [0, 1, 0, .4], [0, 0, 0, 1]]}],
        'map_sha256': 'a'*64,
    }


def synthetic(value, x=0., y=0., yaw=0., identifier=7):
    config = Calibration.parse(value)
    base = np.eye(4)
    base[:2, :2] = [[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]]
    base[:2, 3] = [x, y]
    size, world_marker = config.anchors[7]
    camera_marker = np.linalg.inv(config.base_from_camera) @ np.linalg.inv(base) @ world_marker
    half = size / 2
    points = np.array([[-half, half, 0], [half, half, 0], [half, -half, 0], [-half, -half, 0]])
    projected = cv2.projectPoints(points, cv2.Rodrigues(camera_marker[:3, :3])[0], camera_marker[:3, 3],
                                  config.camera, config.distortion)[0].reshape(4, 2).astype(np.float32)
    marker = cv2.aruco.generateImageMarker(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), identifier, 200)
    transform = cv2.getPerspectiveTransform(np.array([[0, 0], [199, 0], [199, 199], [0, 199]], np.float32), projected)
    canvas = cv2.warpPerspective(marker, transform, (config.width, config.height), borderValue=255)
    return cv2.imencode('.jpg', canvas, [cv2.IMWRITE_JPEG_QUALITY, 95])[1].tobytes()


@pytest.mark.parametrize('x,y,yaw', [(.4, .15, .04), (.8, -.2, -.08), (1., .2, .1), (1.2, -.2, -.1)])
def test_metric_world_pose_from_actual_detected_pixels(x, y, yaw):
    data = fixture()
    result = MarkerLocaliser(Calibration.parse(data)).estimate(synthetic(data, x, y, yaw), frame_key='synthetic-1',
        captured_at_ms=1000, now_ms=1100, camera_fixed=True)
    assert result['state'] == 'located', result
    # This single low-resolution marker is not centimetre-grade localisation.
    # Check the observed metric error without relaxing ambiguity rejection.
    assert math.hypot(result['x_m']-x, result['y_m']-y) < .065
    assert abs(result['yaw_rad']-yaw) < math.radians(2)
    assert result['motion_authorized'] is False
    assert result['marker_ids'] == [7]


def test_frontal_planar_ambiguity_is_rejected_instead_of_guessed():
    data = fixture()
    result = MarkerLocaliser(Calibration.parse(data)).estimate(synthetic(data), frame_key='frontal',
        captured_at_ms=1000, now_ms=1100, camera_fixed=True)
    assert result['state'] == 'unlocated'
    assert result['reason'] == 'marker_pose_rejected_or_ambiguous'


@pytest.mark.parametrize('age', [-1, 501, 10000])
def test_no_stale_or_future_extrapolation(age):
    data = fixture()
    result = MarkerLocaliser(Calibration.parse(data)).estimate(synthetic(data), frame_key='one',
        captured_at_ms=1000, now_ms=1000+age, camera_fixed=True)
    assert result['state'] == 'unlocated'
    assert result['reason'] == 'frame_stale_or_future'


def test_no_fixed_camera_no_pose():
    data = fixture()
    result = MarkerLocaliser(Calibration.parse(data)).estimate(synthetic(data), frame_key='one',
        captured_at_ms=1000, now_ms=1100)
    assert result['reason'] == 'fixed_calibrated_camera_mount_required'


def test_unknown_marker_is_not_location():
    data = fixture()
    result = MarkerLocaliser(Calibration.parse(data)).estimate(synthetic(data, identifier=8), frame_key='one',
        captured_at_ms=1000, now_ms=1100, camera_fixed=True)
    assert result['state'] == 'unlocated'


def test_digest_cannot_silently_outlive_mutated_calibration():
    config = Calibration.parse(fixture())
    with pytest.raises(ValueError):
        config.camera[0, 0] = 5
    with pytest.raises(ValueError):
        config.anchors[7][1][0, 3] = 5
    with pytest.raises(TypeError):
        config.anchors[8] = (.4, np.eye(4))


@pytest.mark.parametrize('change', [
    lambda d: d.update(image_size=[]), lambda d: d.update(map_sha256='bad'),
    lambda d: d.update(distortion=[float('nan')]*5),
    lambda d: d.update(anchors=d['anchors']*2),
    lambda d: d['camera_matrix'][0].__setitem__(0, 0),
    lambda d: d['base_from_camera'][0].__setitem__(0, 1),
    lambda d: d['anchors'][0].update(size_m=True),
])
def test_bad_measurements_rejected(change):
    data = copy.deepcopy(fixture())
    change(data)
    with pytest.raises((ValueError, TypeError)):
        Calibration.parse(data)


@pytest.mark.parametrize('blob', [b'', b'not an image', b'0'*1_500_001], ids=['empty', 'invalid', 'oversize'])
def test_invalid_input_never_location(blob):
    result = MarkerLocaliser(Calibration.parse(fixture())).estimate(blob, frame_key='one', captured_at_ms=1,
        now_ms=2, camera_fixed=True)
    assert result['state'] == 'unlocated'
