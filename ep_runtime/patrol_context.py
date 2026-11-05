"""Idle-only PTZ context photos. No chassis commands; cancellation wins."""
import math
import secrets
import sqlite3
import threading
import time
from collections import deque
from contextlib import closing

from edge_hub.robot_control import ControlError, _read_safety_marker


class PatrolContext:
    def __init__(self, session):
        self.session = session
        self.velocities = deque(maxlen=320)
        self.owner = None
        self.thread = None
        self.cancel = threading.Event()
        self.job = {'state': 'idle'}

    @property
    def busy(self):
        return bool(self.thread and self.thread.is_alive())

    def arm(self):
        s = self.session
        if self.busy:
            raise ControlError('環境攝影仍在進行。', 409)
        if not s.robot or not s.video_enabled:
            raise ControlError('請先開啟即時影像。', 409)
        if self.owner is s.robot:
            return {'armed': True}
        from robomaster.chassis import VelocitySubject

        from ep_runtime.body_snapshot import install_body_decoder
        owner = s.robot
        self.velocities.clear()
        def receive(frame):
            if s.robot is owner and frame.values is not None and len(frame.values) == 6:
                values = tuple(frame.values)
                if all(math.isfinite(value) for value in values):
                    self.velocities.append((frame.decoded_at, values))
        subject = install_body_decoder(VelocitySubject(), 'velocity')
        subject.freq = 10
        if owner.dds.add_subject_info(subject, receive, (), {}) is not True:
            raise ControlError('未能確認底盤速度資料，未轉動雲台。', 503)
        needs_angles = not s.gimbal_angles or time.monotonic()-s.gimbal_angles_at > .5
        if needs_angles and owner.gimbal.sub_angle(freq=10, callback=lambda values: s.receive_gimbal_angles(values) if s.robot is owner else None) is not True:
            raise ControlError('未能確認雲台角度資料。', 503)
        self.owner = owner
        return {'armed': True}

    def ready(self, anchor_ms):
        s = self.session
        now = time.monotonic()
        if self.cancel.is_set() or s.robot is not self.owner or not s.video_enabled or not s.grounded():
            raise ControlError('拍攝已取消或機體狀態未確認。', 409)
        if s.gimbal_driving or s.gimbal_target_angles:
            raise ControlError('請先停止人手雲台操作。', 409)
        if s.control and (s.control.lease or s.control.stop_latched or s.control.state == 'fault'):
            raise ControlError('請先放開方向並確認停止狀態，未轉動雲台。', 409)
        samples = list(self.velocities)
        since = min(now-.7, now-(int(time.time()*1000)-anchor_ms)/1000)
        selected = [item for item in samples if item[0] >= since-.15]
        if (len(selected) < 7 or now-selected[-1][0] > .4 or selected[0][0] > since+.15
                or any(abs(value) > .02 for _, values in selected for value in values)):
            raise ControlError('等待底盤速度資料確認靜止，未轉動雲台。', 409)
        if not s.gimbal_angles or now-s.gimbal_angles_at > .5:
            raise ControlError('雲台角度資料未更新。', 409)

    def start(self, payload):
        if self.busy:
            raise ControlError('正在拍攝左右環境相。', 409)
        s = self.session
        key, anchor_ms, pose = payload.get('frame_key'), payload.get('captured_at_ms'), payload.get('camera_pose')
        if (not isinstance(key, str) or key.split('-')[0] != s.video_epoch or type(anchor_ms) is not int
                or not 0 <= int(time.time()*1000)-anchor_ms <= 20000
                or not isinstance(pose, list) or len(pose) != 2
                or any(type(value) not in (float, int) or not math.isfinite(value) for value in pose)):
            raise ControlError('事件影像或鏡頭角度已過期，請重新辨識。', 409)
        self.cancel = threading.Event()
        self.ready(anchor_ms)
        if any(abs(a-b) > 2 for a, b in zip(pose, s.gimbal_angles)) or not (-20 <= pose[0] <= 25 and -120 <= pose[1] <= 120):
            raise ControlError('鏡頭已改變方向，未以其他位置充當現場環境。', 409)
        filename = f'ep-control-{s.device_id}.sqlite3' if s.device_id else 'ep-control.sqlite3'
        saved = s.root/'.runtime'/filename
        if saved.exists():
            with closing(sqlite3.connect(saved.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                db.row_factory = sqlite3.Row
                marker = _read_safety_marker(db)
                if marker['requires_reset'] or marker['fault']:
                    raise ControlError('停止鎖定仍保留，未轉動雲台。', 423)
        self.job = {'id': secrets.token_hex(12), 'state': 'capturing'}
        def run():
            original_mode = None
            old_follow, old_applied = s.follow_enabled, s.gimbal_mode_applied
            photos = []
            restored = False
            try:
                self.ready(anchor_ms)
                original_mode = s.robot.get_robot_mode()
                if original_mode not in ('free', 'chassis_lead'):
                    raise ControlError('目前機體模式不適合自動拍攝。')
                if s.robot.set_robot_mode(mode='free') is not True or s.robot.get_robot_mode() != 'free':
                    raise ControlError('未確認獨立雲台模式。')
                s.drive_mode = 'free'
                for side, offset in [('left', 30), ('right', -30)]:
                    reached = self.go((pose[0], pose[1]+offset), anchor_ms)
                    deadline = time.monotonic()+2
                    while time.monotonic() < deadline:
                        self.ready(anchor_ms)
                        frame = getattr(s, 'video_snapshot', None)
                        if frame and frame['read_at'] > reached+.3 and frame['frame_key'].split('-')[0] == key.split('-')[0]:
                            photos.append({k: frame[k] for k in ('jpeg_base64', 'frame_key', 'captured_at_ms', 'camera_pose')})
                            photos[-1].update(side=side, yaw_offset_degrees=offset)
                            break
                        self.cancel.wait(.05)
                    else:
                        raise ControlError('左右環境相片未更新。')
            except Exception:  # noqa: BLE001 -- never turn a failed photo into a synthetic side view
                self.job['error'] = '環境攝影未完成；請停穩並留空雲台周圍，再由現場核實。'
            finally:
                if original_mode and s.robot is self.owner and not self.cancel.is_set():
                    try:
                        self.go(tuple(pose), anchor_ms)
                        restored = s.robot.set_robot_mode(mode=original_mode) is True and s.robot.get_robot_mode() == original_mode
                    except Exception:  # noqa: BLE001
                        restored = False
                if restored and s.robot is self.owner:
                    s.drive_mode, s.follow_enabled, s.gimbal_mode_applied = original_mode, old_follow, old_applied
                elif original_mode and s.robot is self.owner:
                    s.drive_mode, s.follow_enabled, s.gimbal_mode_applied = 'free', False, False
                complete = len(photos) == 2 and restored and not self.cancel.is_set()
                self.job.update(state='completed' if complete else 'unconfirmed', restored=restored,
                                photos=photos if complete else [])
        self.thread = threading.Thread(target=run, daemon=True, name='ep-context-photos')
        self.thread.start()
        return {'job_id': self.job['id'], 'state': 'capturing'}

    def go(self, target, anchor_ms):
        s = self.session
        deadline = time.monotonic()+4.5
        try:
            while time.monotonic() < deadline:
                self.ready(anchor_ms)
                pitch, yaw = s.gimbal_angles
                error = (target[0]-pitch, target[1]-yaw)
                if abs(error[0]) <= 1.5 and abs(error[1]) <= 1.5:
                    return time.monotonic()
                if s.robot.gimbal.drive_speed(pitch_speed=max(-10, min(10, error[0]*2)), yaw_speed=max(-25, min(25, error[1]*2))) is not True:
                    raise ControlError('雲台轉動發送未確認。')
                self.cancel.wait(.05)
            raise ControlError('雲台角度未到達，未拍攝替代相片。')
        finally:
            if s.robot is self.owner:
                s.robot.gimbal.drive_speed(pitch_speed=0, yaw_speed=0)

    def snapshot(self, job_id=None):
        if job_id and self.job.get('id') != job_id:
            raise ControlError('環境攝影工作已更新。', 409)
        return dict(self.job)

    def stop(self):
        self.cancel.set()
