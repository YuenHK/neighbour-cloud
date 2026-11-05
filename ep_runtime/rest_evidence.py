"""Bounded encoder uncertainty and RPM consistency, never a physical-stop proof."""
from collections import deque
from statistics import median


class RestEvidence:
    PERIOD = 32768  # DJI ESC angle: 0..32767 for a full revolution.
    WINDOW = 2.0
    MAX_SPAN = 4  # fixed raw encoder counts, about .044 degrees, not adaptive
    MAX_TREND = .5  # raw counts/second
    RPM_LIMIT = 6  # unchanged; no higher RPM is relabelled as zero
    MAX_ISOLATED_RPM = 18  # bounded experimental outlier rule, never auto-calibrated

    def __init__(self):
        self.frames = deque(maxlen=64)
        self.last_angles = None
        self.unwrapped = None
        self.anchor = None
        self.excursion_runs = [None] * 4
        self.blocked = None
        self.blocked_evidence = None
        self.first_signal_anomaly = None
        self.signal_recovery_after = None
        self.signal_recovery_pending = False
        self.signal_recoveries = 0
        self.reason = 'collecting_rest_samples'
        self.metrics = {}

    def invalidate(self, reason):
        stamp = self.frames[-1][0] if self.frames else None
        self.frames.clear()
        self.reason = reason
        self.signal_anomaly(reason, {'kind': 'data_quality'}, stamp)
        self.excursion_runs = [None] * 4

    def signal_anomaly(self, reason, evidence, stamp):
        if self.first_signal_anomaly is None:
            self.first_signal_anomaly = {'reason': reason, **evidence, 'sample_time': stamp}
        if stamp is not None:
            self.signal_recovery_after = max(stamp, self.signal_recovery_after or stamp)
        self.signal_recovery_pending = True

    def block(self, reason, evidence):
        if self.blocked is None:
            self.blocked = reason
            self.blocked_evidence = {'reason': reason, **evidence}

    def add(self, stamp, speeds, angles):
        if self.last_angles is None:
            self.unwrapped = tuple(angles)
        else:
            delta = tuple((new - old + self.PERIOD // 2) % self.PERIOD - self.PERIOD // 2
                          for new, old in zip(angles, self.last_angles, strict=True))
            self.unwrapped = tuple(old + step for old, step in zip(self.unwrapped, delta, strict=True))
        self.last_angles = tuple(angles)
        if self.anchor is not None:
            for wheel, (value, origin) in enumerate(zip(self.unwrapped, self.anchor, strict=True)):
                offset = value - origin
                if abs(offset) <= self.MAX_SPAN:
                    self.excursion_runs[wheel] = None
                    continue
                direction = 1 if offset > 0 else -1
                run = self.excursion_runs[wheel]
                if run is None or run['direction'] != direction:
                    run = {'direction': direction, 'since': stamp, 'samples': 0}
                    self.excursion_runs[wheel] = run
                run['samples'] += 1
                if run['samples'] >= 3 and stamp - run['since'] >= .2 - 1e-9:
                    self.block('encoder_drift_since_rest', {
                        'kind': 'sustained_reference_excursion', 'wheel_index': wheel,
                        'reference_count': origin, 'observed_count': value,
                        'offset_counts': offset, 'confirmed_samples': run['samples'],
                        'confirmed_ms': round((stamp - run['since']) * 1000), 'sample_time': stamp})
        self.frames.append((stamp, tuple(speeds), self.unwrapped))
        while self.frames and stamp - self.frames[0][0] > 2.5:
            self.frames.popleft()

    def evaluate(self):
        frames = list(self.frames)
        span = frames[-1][0] - frames[0][0] if frames else 0
        self.metrics = {'window_samples': len(frames), 'window_ms': round(span * 1000)}
        if len(frames) < 16 or span < self.WINDOW:
            self.reason = self.blocked or 'collecting_rest_samples'
            return False
        means_t = sum(row[0] - frames[0][0] for row in frames) / len(frames)
        time_var = sum((row[0] - frames[0][0] - means_t)**2 for row in frames)
        spans, trends, outliers, centers = [], [], [], []
        for wheel in range(4):
            angles = [row[2][wheel] for row in frames]
            rpms = [abs(row[1][wheel]) for row in frames]
            width = max(angles) - min(angles)
            mean_angle = sum(angles) / len(angles)
            trend = sum((row[0] - frames[0][0] - means_t) * (angle - mean_angle)
                        for row, angle in zip(frames, angles, strict=True)) / time_var
            spans.append(width)
            trends.append(trend)
            centers.append(median(angles))
            outliers.append(sum(rpm > self.RPM_LIMIT for rpm in rpms))
        # Always publish the CURRENT complete window, even after a hard block.
        # The first trigger is retained separately and cannot be overwritten.
        self.metrics.update({'encoder_span_counts': spans,
                             'encoder_trend_counts_s': [round(value, 4) for value in trends],
                             'encoder_center_counts': centers, 'rpm_outside_normal_samples': outliers,
                             'encoder_reference_counts': self.anchor,
                             'encoder_center_within_reference': self.anchor is not None and all(
                                 abs(center - origin) <= self.MAX_SPAN
                                 for center, origin in zip(centers, self.anchor, strict=True)),
                             'encoder_reference_offset_counts':
                             [center - origin for center, origin in zip(centers, self.anchor, strict=True)]
                             if self.anchor is not None else None})
        if self.blocked:
            self.reason = self.blocked
            return False
        if self.anchor is not None:
            for wheel, (center, origin) in enumerate(zip(centers, self.anchor, strict=True)):
                if abs(center - origin) > self.MAX_SPAN:
                    self.block('encoder_drift_since_rest', {
                        'kind': 'reference_center_shift', 'wheel_index': wheel,
                        'reference_count': origin, 'observed_count': center,
                        'offset_counts': center - origin, 'window_ms': round(span * 1000),
                        'sample_time': frames[-1][0]})
                    self.reason = self.blocked
                    return False
        for wheel in range(4):
            angles = [row[2][wheel] for row in frames]
            rpms = [abs(row[1][wheel]) for row in frames]
            width, trend = spans[wheel], trends[wheel]
            if width > self.MAX_SPAN:
                self.reason = 'encoder_excursion'
                return False
            if abs(trend) > self.MAX_TREND or abs(median(angles[:5]) - median(angles[-5:])) > 1:
                self.reason = 'encoder_directional_drift'
                return False
            bad = [index for index, rpm in enumerate(rpms) if rpm > self.RPM_LIMIT]
            if (max(rpms) > self.MAX_ISOLATED_RPM or median(rpms) > self.RPM_LIMIT
                    or len(bad) * 4 > len(frames)):
                self.reason = 'rpm_inconsistent'
                self.signal_anomaly(self.reason, {
                    'kind': 'rpm_quality', 'wheel_index': wheel, 'max_abs_rpm': max(rpms),
                    'outside_normal_samples': len(bad)}, max(frames[index][0] for index in bad))
                return False
            for index in bad:
                # A current spike, a burst, or a spike accompanied by actual
                # encoder travel cannot be filtered into stationary evidence.
                if (index == 0 or index == len(frames) - 1
                        or rpms[index - 1] > self.RPM_LIMIT or rpms[index + 1] > self.RPM_LIMIT
                        or abs(angles[index] - angles[index - 1]) > 2
                        or abs(angles[index + 1] - angles[index]) > 2):
                    self.reason = 'rpm_unresolved_spike'
                    provisional_tail = (index == len(frames) - 1 and index > 0
                                        and rpms[index - 1] <= self.RPM_LIMIT
                                        and abs(angles[index] - angles[index - 1]) <= 2)
                    if not provisional_tail:
                        self.signal_anomaly(self.reason, {'kind': 'unresolved_rpm_spike', 'wheel_index': wheel,
                                                         'max_abs_rpm': rpms[index]}, frames[index][0])
                    return False
        # All original quality checks must pass using samples entirely AFTER the
        # unknown interval/spike. Neither the fixed origin nor hard blocks move.
        if self.signal_recovery_pending:
            if self.signal_recovery_after is not None and frames[0][0] <= self.signal_recovery_after:
                self.reason = 'rebuilding_after_signal_anomaly'
                return False
            self.signal_recovery_pending = False
            self.signal_recoveries += 1
        if self.anchor is None:
            self.anchor = tuple(centers)
            self.metrics['encoder_reference_counts'] = self.anchor
            self.metrics['encoder_reference_offset_counts'] = [0.] * 4
            self.metrics['encoder_center_within_reference'] = True
        self.metrics['isolated_rpm_outliers'] = outliers  # only labelled after corroboration
        self.reason = 'bounded_stationary_evidence'
        return True
