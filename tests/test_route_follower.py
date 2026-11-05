import math

import pytest

from edge_hub.route_follower import RouteFollower


def follower():
    return RouteFollower(path=[(2, 2), (3, 2), (4, 2)], cell_m=.5,
        allowed={(x, y) for x in range(1, 6) for y in range(1, 5)},
        map_sha256='a'*64, calibration_sha256='b'*64)


def pose(x=1.25, y=1.25, at=1000, yaw=0.):
    return {'state': 'located', 'x_m': x, 'y_m': y, 'yaw_rad': yaw,
        'frame_key': f'frame-{at}', 'captured_at_ms': at, 'map_sha256': 'a'*64, 'calibration_sha256': 'b'*64}


def tick(f, p=None, at=1000, free=None, observed=1000):
    return f.tick(now_ms=at, pose=p or pose(at=at), observed_free=free if free is not None else
        {(x, y) for x in range(7) for y in range(7)}, observed_at_ms=observed)


def test_closed_loop_reaches_waypoints_without_actuator():
    f = follower()
    x, y, now = 1.25, 1.25, 1000
    for _ in range(200):
        result = tick(f, pose(x, y, at=now), now, observed=now)
        assert result['hardware_commands'] == 0 and not result['execution_enabled']
        assert math.hypot(result['body_vx_mps'], result['body_vy_mps']) <= .15000001
        if result['state'] == 'arrived':
            break
        x += result['body_vx_mps']*.1
        y += result['body_vy_mps']*.1
        now += 100
    assert result['state'] == 'arrived'
    assert abs(x-2.25) < .07


@pytest.mark.parametrize('change,reason', [
    (lambda p: p.update(state='unlocated'), 'fresh_matching_localisation_required'),
    (lambda p: p.update(map_sha256='c'*64), 'fresh_matching_localisation_required'),
    (lambda p: p.update(calibration_sha256='c'*64), 'fresh_matching_localisation_required'),
    (lambda p: p.update(captured_at_ms=1), 'localisation_stale_future_or_reordered'),
    (lambda p: p.update(captured_at_ms=1001), 'localisation_stale_future_or_reordered'),
    (lambda p: p.update(x_m=float('nan')), 'invalid_pose'),
    (lambda p: p.update(x_m=10**1000), 'invalid_pose'),
    (lambda p: p.update(x_m=-1), 'outside_surveyed_clearance'),
])
def test_bad_pose_latches_stop(change, reason):
    f, p = follower(), pose()
    change(p)
    assert tick(f, p)['state'] == reason
    assert tick(f, at=1100, observed=1100)['body_vx_mps'] == 0
    assert f.stopped == reason


def test_map_is_not_obstacle_sensor():
    f = follower()
    assert tick(f, free={(2, 2)})['state'] == 'obstacle_or_unobserved_footprint'


def test_obstacle_loss_and_pose_jump_stop():
    f = follower()
    tick(f)
    assert tick(f, pose(1.9, 1.25, at=1100), 1100, observed=1100)['state'] == 'localisation_jump'
    assert tick(f, at=1200, observed=1200)['body_vx_mps'] == 0


def test_stale_sensor_and_clock_regression():
    assert tick(follower(), at=1500, observed=1000)['state'] == 'live_clearance_missing_or_stale'
    f = follower()
    tick(f)
    assert tick(f, at=999)['state'] == 'clock_not_increasing'


def test_body_velocity_transforms_world_heading():
    f = follower()
    tick(f)
    result = tick(f, pose(at=1100, yaw=math.pi/2), at=1100, observed=1100)
    assert abs(result['body_vx_mps']) < 1e-8
    assert result['body_vy_mps'] < 0


def test_same_timestamp_cannot_hide_changed_pose():
    f = follower()
    tick(f)
    result = tick(f, pose(2.25, 1.25, at=1000), at=1100, observed=1100)
    assert result['state'] == 'replayed_or_changed_frame'
    assert result['body_vx_mps'] == 0


def test_route_must_start_at_the_confirmed_first_waypoint():
    f = follower()
    result = tick(f, pose(2.25, 1.25))
    assert result['state'] == 'route_start_confirmation_required'
    assert result['body_vx_mps'] == 0


def test_deviation_from_segment_cannot_drive_through_unsurveyed_corridor():
    f = follower()
    tick(f)
    # A nearby centre still inside allowed cells is not necessarily on route.
    result = tick(f, pose(1.25, 1.36, at=1100), at=1100, observed=1100)
    assert result['state'] == 'outside_current_route_segment'


def test_relabelled_cached_frame_cannot_refresh_localisation():
    f = follower()
    tick(f)
    reused = pose(at=1100)
    reused['frame_key'] = 'frame-1000'
    assert tick(f, reused, at=1100, observed=1100)['state'] == 'replayed_or_changed_frame'
