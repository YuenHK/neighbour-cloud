"""Release evidence in body coordinates, with a separate wheel-rotation guard.

These are explicit engineering acceptance bounds, not sensor accuracy claims.
No method in this module can send hardware commands or clear controller faults.
"""
import math
from collections import deque
from itertools import pairwise
from statistics import median

from ep_runtime.body_snapshot import BodySnapshot
from ep_runtime.rest_evidence import RestEvidence


class ReleaseEvidence:
    WINDOW = 2.
    FRESH = .25
    POSITION_M = .001  # 1 mm body envelope, not individual motor-angle counts
    YAW_DEG = .1
    POSITION_TICKS = 100  # SDK public position decimal=5: 100 units = 1mm
    YAW_TICKS = 10  # SDK public yaw decimal=2: 10 units = .1 degree
    PERIOD = RestEvidence.PERIOD
    RPM_LIMIT = RestEvidence.RPM_LIMIT
    MAX_ISOLATED_RPM = RestEvidence.MAX_ISOLATED_RPM
    WHEEL_RPM_RESOLUTION = 1.  # published ESC speed is integer RPM

    def __init__(self, after=0.):
        self.after = after
        self.body = {topic: deque(maxlen=64) for topic in ('position', 'attitude', 'velocity')}
        self.serials = {}
        self.wheels = deque(maxlen=64)
        self.last_angles = self.unwrapped = None
        self.body_reference = None
        self.body_runs = [None] * 3
        self.first_block = None
        self.first_anomaly = None
        self.phase = 'holding'
        self.reason = 'waiting_body_telemetry'
        self.metrics = {}

    def anomaly(self, reason):
        if self.first_anomaly is None:
            self.first_anomaly = {'reason': reason}
        self.reason = reason

    @staticmethod
    def trim(rows, now):
        while rows and now - rows[0][0] > 2.5:
            rows.popleft()

    def invalidate_wheels(self, reason):
        self.wheels.clear()
        self.anomaly(reason)

    def transition(self, after, phase):
        # A mode ACK creates a new wheel-feedback epoch, not a new body origin.
        self.after, self.phase = after, phase
        self.wheels.clear()
        self.last_angles = self.unwrapped = None
        for rows in self.body.values():
            rows.clear()
        self.body_runs = [None] * 3
        self.metrics = {'phase': phase}
        self.reason = 'rebuilding_mode_epoch'

    def add_body(self, frame, now):
        if not isinstance(frame, BodySnapshot) or frame.topic not in self.body:
            return
        rows = self.body[frame.topic]
        if (type(frame.decoded_at) not in (int, float) or not math.isfinite(frame.decoded_at)
                or type(frame.serial) is not int or frame.values is None
                or not all(type(v) in (int, float) and math.isfinite(v) for v in frame.values)
                or len(frame.values) != (6 if frame.topic == 'velocity' else 3)
                or not 0 <= now - frame.decoded_at < self.FRESH):
            rows.clear()
            self.anomaly('invalid_or_stale_body_snapshot')
            return
        if frame.decoded_at < self.after:
            return
        if frame.serial <= self.serials.get(frame.topic, -1):
            return  # duplicate callback cannot refresh freshness
        self.serials[frame.topic] = frame.serial
        if rows and frame.decoded_at - rows[-1][0] > self.FRESH:
            rows.clear()
            self.anomaly('body_sample_gap')
        values = tuple(frame.values)
        if frame.topic == 'position':
            values = (round(values[0] * 100000), round(values[1] * 100000), values[2])
        elif frame.topic == 'attitude':
            if any(abs(v) > 180 for v in values):
                rows.clear()
                self.anomaly('invalid_body_attitude')
                return
            values = tuple(round(value * 100) for value in values)
            previous_yaw = (rows[-1][1][0] if rows else self.body_reference[2]
                            if self.body_reference is not None else values[0])
            values = (previous_yaw + (values[0] - previous_yaw + 18000) % 36000 - 18000, *values[1:])
        rows.append((frame.decoded_at, values))
        self.trim(rows, frame.decoded_at)
        self.check_body_departure(frame.topic, frame.decoded_at, values)

    def check_body_departure(self, topic, stamp, values):
        if self.body_reference is None or topic == 'velocity':
            return
        axes = ((0, values[0], self.POSITION_TICKS), (1, values[1], self.POSITION_TICKS)) if topic == 'position' else ((2, values[0], self.YAW_TICKS),)
        for axis, value, limit in axes:
            offset = value - self.body_reference[axis]
            if abs(offset) <= limit:
                self.body_runs[axis] = None
                continue
            direction = 1 if offset > 0 else -1
            run = self.body_runs[axis]
            if run is None or run['direction'] != direction:
                run = {'direction': direction, 'since': stamp, 'samples': 0}
                self.body_runs[axis] = run
            run['samples'] += 1
            if (self.first_block is None and run['samples'] >= 3
                    and stamp - run['since'] >= .2 - 1e-9):
                self.first_block = {'reason': 'confirmed_body_departure', 'axis': axis,
                                    'offset': offset, 'limit': limit, 'sample_time': stamp}

    def add_wheels(self, stamp, speeds, angles):
        if stamp < self.after:
            return
        if self.last_angles is None:
            self.unwrapped = tuple(angles)
        else:
            self.unwrapped = tuple(old + (new - last + self.PERIOD // 2) % self.PERIOD - self.PERIOD // 2
                                   for old, new, last in zip(self.unwrapped, angles, self.last_angles, strict=True))
        self.last_angles = tuple(angles)
        self.wheels.append((stamp, tuple(speeds), self.unwrapped))
        # Retain one predecessor outside the measurement window. A window edge
        # is not a telemetry gap and must not erase a spike's real neighbour.
        while len(self.wheels) > 2 and stamp - self.wheels[1][0] > 2.5:
            self.wheels.popleft()

    def check_rpm(self, start):
        rows = list(self.wheels)
        indices = [i for i, row in enumerate(rows) if row[0] >= start]
        outside = []
        for wheel in range(4):
            rpms = [abs(rows[i][1][wheel]) for i in indices]
            bad = [i for i in indices if abs(rows[i][1][wheel]) > self.RPM_LIMIT]
            outside.append(len(bad))
            if max(rpms) > self.MAX_ISOLATED_RPM or median(rpms) > self.RPM_LIMIT or len(bad)*4 > len(indices):
                self.metrics['rpm_blocker'] = {'kind': 'rpm_quality', 'wheel': wheel,
                                               'max_abs_rpm': max(rpms), 'outside_samples': len(bad)}
                self.reason = 'wheel_rpm_quality'
                return False
            for index in bad:
                row = rows[index]
                neighbours = rows[max(0, index-1):index+2]
                evidence = {'wheel': wheel, 'rpm': row[1][wheel], 'sample_time': row[0],
                            'at_window_start': index == indices[0],
                            'at_latest_sample': index == len(rows)-1,
                            'neighbour_rpm': [r[1][wheel] for r in neighbours],
                            'neighbour_angles': [r[2][wheel] for r in neighbours]}
                if (index == 0 or index == len(rows)-1
                        or abs(rows[index-1][1][wheel]) > self.RPM_LIMIT
                        or abs(rows[index+1][1][wheel]) > self.RPM_LIMIT
                        or not 0 < row[0]-rows[index-1][0] < self.FRESH
                        or not 0 < rows[index+1][0]-row[0] < self.FRESH
                        or abs(row[2][wheel]-rows[index-1][2][wheel]) > 2
                        or abs(rows[index+1][2][wheel]-row[2][wheel]) > 2):
                    self.metrics['rpm_blocker'] = evidence
                    self.reason = 'wheel_spike_unresolved'
                    return False
        self.metrics['wheel_rpm_outside_normal_samples'] = outside
        return True

    def evaluate(self, now):
        self.metrics = {'phase': self.phase, 'body_reference_ticks': self.body_reference,
                        'body_topics': {topic: {'samples': len(rows),
                            'age_ms': round((now - rows[-1][0]) * 1000) if rows else None}
                            for topic, rows in self.body.items()}}
        if self.first_block:
            self.reason = 'confirmed_body_departure'
            return False
        sets = [*self.body.values(), self.wheels]
        if any(not rows or now - rows[-1][0] >= self.FRESH for rows in sets):
            self.reason = 'waiting_body_telemetry'
            return False
        if max(rows[-1][0] for rows in sets) - min(rows[-1][0] for rows in sets) > self.FRESH:
            self.reason = 'body_wheel_time_mismatch'
            return False
        if any(len(rows) < 16 or rows[-1][0] - rows[0][0] < self.WINDOW for rows in sets):
            self.reason = 'collecting_body_window'
            return False
        start = max(*(rows[0][0] for rows in sets), self.wheels[1][0])
        end = min(rows[-1][0] for rows in sets)
        aligned = {name: [row for row in rows if start <= row[0] <= end] for name, rows in self.body.items()}
        wheel_frames = [row for row in self.wheels if start <= row[0] <= end]
        if end - start < self.WINDOW or any(len(rows) < 16 for rows in [*aligned.values(), wheel_frames]):
            self.reason = 'collecting_body_window'
            return False
        # Classify the FULL ESC context once, including newer samples beyond the
        # body-topic overlap. Do not discard neighbours by slicing each topic.
        if not self.check_rpm(start):
            return False
        # Do not hide newer wheel motion merely because another body topic lags.
        for left, right in pairwise(self.wheels):
            if right[0] < end:
                continue
            edge = right[0] - left[0]
            if edge <= 0 or any(abs(b - a) * 60 / (self.PERIOD * edge) >= self.WHEEL_RPM_RESOLUTION
                                for a, b in zip(left[2], right[2], strict=True)):
                self.reason = 'wheel_rotation_in_window'
                return False
        positions = aligned['position']
        attitude = aligned['attitude']
        spans = [max(row[1][axis] for row in positions) - min(row[1][axis] for row in positions) for axis in (0, 1)]
        yaw_span = max(row[1][0] for row in attitude) - min(row[1][0] for row in attitude)
        center = (median(row[1][0] for row in positions), median(row[1][1] for row in positions),
                  median(row[1][0] for row in attitude))
        self.metrics.update({'body_xy_span_m': [value / 100000 for value in spans], 'body_yaw_span_deg': yaw_span / 100,
                             'body_center': (center[0] / 100000, center[1] / 100000, center[2] / 100),
                             'position_envelope_m': self.POSITION_M,
                             'yaw_envelope_deg': self.YAW_DEG})
        if any(value > self.POSITION_TICKS for value in spans) or yaw_span > self.YAW_TICKS:
            self.reason = 'body_motion_in_window'
            return False
        if self.body_reference is not None and any(abs(value - origin) > limit
                for value, origin, limit in zip(center, self.body_reference,
                                                (self.POSITION_TICKS, self.POSITION_TICKS, self.YAW_TICKS), strict=True)):
            self.reason = 'body_reference_mismatch'
            return False
        reference = self.body_reference if self.body_reference is not None else center
        latest = (*self.body['position'][-1][1][:2], self.body['attitude'][-1][1][0])
        if any(abs(value - origin) > limit for value, origin, limit in zip(
                latest, reference, (self.POSITION_TICKS, self.POSITION_TICKS, self.YAW_TICKS), strict=True)):
            self.reason = 'body_motion_current'
            return False
        # Match the SDK's public linear-velocity representation (2 decimals),
        # while retaining raw floats in the immutable snapshots. Position/yaw
        # guard against slow motion below that velocity representation.
        if any(round(row[1][axis], 2) != 0 for row in self.body['velocity'] for axis in (0, 1, 3, 4)):
            self.reason = 'body_velocity_nonzero'
            return False
        span = wheel_frames[-1][0] - wheel_frames[0][0]
        rates = []
        for wheel in range(4):
            angles = [row[2][wheel] for row in wheel_frames]
            path = sum(abs(b - a) for a, b in pairwise(angles))
            rate = path * 60 / (self.PERIOD * span)
            rates.append(rate)
            if rate >= self.WHEEL_RPM_RESOLUTION:
                self.reason = 'wheel_rotation_in_window'
                return False
        if self.body_reference is None:
            self.body_reference = center
        self.metrics.update({'body_reference_ticks': self.body_reference, 'wheel_path_rpm': rates,
                             'window_ms': round((end - start) * 1000)})
        self.reason = 'body_and_wheels_stationary'
        return True
