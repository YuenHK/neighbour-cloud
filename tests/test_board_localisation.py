import copy
import math

import numpy as np
import pytest

from edge_hub.board_localisation import BoardLocaliser
from edge_hub.fiducial_localisation import Calibration
from tools.navigation_board_lab import render_frame, synthetic_calibration


@pytest.mark.parametrize('nonplanar', [False, True])
@pytest.mark.parametrize('x,y,yaw', [(.3, -.12, -.04), (.6, .12, .04)])
def test_actual_multi_marker_pixels_recover_metric_pose(nonplanar, x, y, yaw):
    value = synthetic_calibration(nonplanar=nonplanar)
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value, x=x, y=y, yaw=yaw, noise=1.5),
        frame_key='synthetic', captured_at_ms=1000, now_ms=1100, camera_fixed=True)
    assert result['state'] == 'located', result
    assert math.hypot(result['x_m']-x, result['y_m']-y) < .025
    assert abs(result['yaw_rad']-yaw) < math.radians(1.5)
    assert result['marker_ids'] == [7, 8]
    assert result['method'] == ('joint_nonplanar_sqpnp' if nonplanar else 'joint_planar_ippe')
    assert not result['motion_authorized'] and not result['is_real_world_accuracy_guarantee']


def test_planar_frontal_two_markers_still_reject_an_actual_ambiguous_jpeg():
    value = synthetic_calibration()
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value, noise=1.5),
        frame_key='planar-frontal', captured_at_ms=1000, now_ms=1100, camera_fixed=True)
    assert result['state'] == 'unlocated'
    assert result['reason'] == 'joint_pose_ambiguous'


def test_nonplanar_geometry_can_recover_the_frontal_pose():
    value = synthetic_calibration(nonplanar=True)
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value, noise=1.5),
        frame_key='nonplanar-frontal', captured_at_ms=1000, now_ms=1100, camera_fixed=True)
    assert result['state'] == 'located', result
    assert math.hypot(result['x_m'], result['y_m']) < .025


@pytest.mark.parametrize('visible', [(7,), (8,), ()])
def test_partial_or_missing_board_has_no_implicit_single_marker_fallback(visible):
    value = synthetic_calibration()
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value, visible=visible),
        frame_key='one', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['state'] == 'unlocated'


def test_unknown_identity_does_not_supply_second_surveyed_anchor():
    value = synthetic_calibration()
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value, labels={8: 9}),
        frame_key='one', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['state'] == 'unlocated'


def test_duplicate_identity_rejected_even_with_different_marker_locations():
    value = synthetic_calibration()
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value, labels={8: 7}),
        frame_key='one', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['reason'] == 'duplicate_marker_identity'


@pytest.mark.parametrize('change', [.3, -.3])
def test_inconsistent_survey_is_not_hidden_by_dropping_bad_marker(change):
    value = synthetic_calibration()
    wrong = copy.deepcopy(value)
    wrong['anchors'][1]['world_from_marker'][1][3] += change
    result = BoardLocaliser(Calibration.parse(wrong)).estimate(render_frame(value),
        frame_key='one', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['state'] == 'unlocated', result


@pytest.mark.parametrize('now, fixed, why', [
    (0, True, 'frame_stale_or_future'), (502, True, 'frame_stale_or_future'),
    (2, False, 'fixed_calibrated_camera_mount_required'),
])
def test_original_freshness_and_mount_guards_remain(now, fixed, why):
    value = synthetic_calibration()
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value),
        frame_key='one', captured_at_ms=1, now_ms=now, camera_fixed=fixed)
    assert result['reason'] == why


def test_world_axis_transforms_are_rigid_and_no_camera_mount_is_guessed():
    value = synthetic_calibration(nonplanar=True)
    config = Calibration.parse(value)
    assert np.linalg.det(config.base_from_camera[:3, :3]) == pytest.approx(1.)
    assert not config.base_from_camera.flags.writeable
    result = BoardLocaliser(config).estimate(render_frame(value), frame_key='one', captured_at_ms=1, now_ms=2)
    assert result['reason'] == 'fixed_calibrated_camera_mount_required'


def test_many_decoded_coplanar_pixels_are_not_automatically_good_geometry():
    value = synthetic_calibration()
    for row, lateral in zip(value['anchors'], [-.2, .2]):
        row['size_m'] = .2
        row['world_from_marker'][0][3] = 4.
        row['world_from_marker'][1][3] = lateral
        row['world_from_marker'][2][3] = .25
    result = BoardLocaliser(Calibration.parse(value)).estimate(render_frame(value),
        frame_key='weak-depth', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['state'] == 'unlocated'
    assert result['reason'] in ('joint_pose_ambiguous', 'joint_pose_rejected_or_poorly_observable')


@pytest.mark.parametrize('blob', [b'', b'not-jpeg', b'x'*1_500_001], ids=['empty', 'invalid', 'oversize'])
def test_byte_bound_and_jpeg_only_contract(blob):
    result = BoardLocaliser(Calibration.parse(synthetic_calibration())).estimate(blob,
        frame_key='invalid', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['state'] == 'unlocated'


def test_saved_jpeg_analysis_does_not_open_any_device_or_network(monkeypatch):
    import socket

    import cv2
    value = synthetic_calibration(nonplanar=True)
    image = render_frame(value)

    def forbidden(*args, **kwargs):
        raise AssertionError('hardware_or_network_access')

    monkeypatch.setattr(cv2, 'VideoCapture', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'getaddrinfo', forbidden)
    result = BoardLocaliser(Calibration.parse(value)).estimate(image,
        frame_key='offline', captured_at_ms=1, now_ms=2, camera_fixed=True)
    assert result['state'] == 'located'
