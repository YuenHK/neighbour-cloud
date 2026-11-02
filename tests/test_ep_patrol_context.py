import time
from types import SimpleNamespace

import pytest

from edge_hub.robot_control import ControlError
from ep_runtime.patrol_context import PatrolContext


def context(tmp_path):
    calls = []
    robot = SimpleNamespace(get_robot_mode=lambda: 'free',
                            set_robot_mode=lambda **kw: calls.append(kw) or True)
    session = SimpleNamespace(robot=robot, video_enabled=True, grounded=lambda: True,
        gimbal_driving=False, gimbal_target_angles=None, control=None, gimbal_angles=(0, 0),
        gimbal_angles_at=time.monotonic(), video_epoch='epoch', root=tmp_path,
        device_id='ep-2', follow_enabled=True, gimbal_mode_applied=True)
    capture = PatrolContext(session)
    capture.owner = robot
    now = time.monotonic()
    capture.velocities.extend((now-.7+i*.1, (0,)*6) for i in range(8))
    return capture, session, calls


def test_actual_two_views_and_restore_require_no_chassis_calls(tmp_path):
    capture, session, calls = context(tmp_path)
    poses = []
    def go(pose, anchor):
        poses.append(pose)
        session.gimbal_angles = pose
        session.video_snapshot = {'jpeg_base64': 'synthetic', 'frame_key': f'epoch-{len(poses)}',
            'captured_at_ms': anchor+len(poses), 'camera_pose': pose, 'read_at': time.monotonic()+1}
        return time.monotonic()
    capture.go = go
    capture.start({'frame_key': 'epoch-0', 'captured_at_ms': int(time.time()*1000), 'camera_pose': [0, 0]})
    capture.thread.join(2)
    assert poses == [(0, 30), (0, -30), (0, 0)]
    assert capture.snapshot()['state'] == 'completed'
    assert {p['side'] for p in capture.snapshot()['photos']} == {'left', 'right'}
    assert calls == [{'mode': 'free'}, {'mode': 'free'}]


@pytest.mark.parametrize('reason', ['lease', 'moving', 'stale', 'cancelled'])
def test_unconfirmed_stationary_never_starts_camera_motion(tmp_path, reason):
    capture, session, calls = context(tmp_path)
    if reason == 'lease':
        session.control = SimpleNamespace(lease=object(), stop_latched=False, state='ready')
    elif reason == 'moving':
        capture.velocities.append((time.monotonic(), (1, 0, 0, 0, 0, 0)))
    elif reason == 'stale':
        session.gimbal_angles_at -= 5
    else:
        capture.stop()
    with pytest.raises(ControlError):
        capture.ready(int(time.time()*1000))
    assert not calls and not capture.busy
