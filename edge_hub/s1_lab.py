"""Official S1 Lab read-only snapshot template and manual import validation.

The S1's power-on coordinates are odometry, not a surveyed map pose. This
module does not connect to the S1, enable vision, or send movement commands.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise

LAB_SOURCE = "dji-s1-lab-manual"
GUIDE_URL = "https://www.dji.com/robomaster-s1/programming-guide"
MAX_IMPORT_BYTES = 4096


def readonly_lab_script() -> str:
    """Single bounded read; operator must run it in official Lab themselves.

    The globals can be inspected with Lab's variable/FPV monitor. No console,
    network, file export or on-robot JSON support is assumed.
    """
    return '''# Neighbour S1 read-only snapshot, official RoboMaster Lab only.
# Not a network bridge. Do not enable as a power-on autonomous program.
# Inspect these variables in the Lab/FPV variable monitor after running once.
# Power-on coordinates are raw odometry; units/frame need field validation.
neighbour_uptime = 0
neighbour_forward = 0
neighbour_translation = 0
neighbour_rotation = 0
neighbour_yaw = 0
neighbour_pitch = 0
neighbour_roll = 0

def start():
    global neighbour_uptime, neighbour_forward, neighbour_translation
    global neighbour_rotation, neighbour_yaw, neighbour_pitch, neighbour_roll
    neighbour_uptime = tools.get_unixtime()
    neighbour_forward = chassis_ctrl.get_position_based_power_on(rm_define.chassis_forward)
    neighbour_translation = chassis_ctrl.get_position_based_power_on(rm_define.chassis_translation)
    neighbour_rotation = chassis_ctrl.get_position_based_power_on(rm_define.chassis_rotate)
    neighbour_yaw = chassis_ctrl.get_attitude(rm_define.chassis_yaw)
    neighbour_pitch = chassis_ctrl.get_attitude(rm_define.chassis_pitch)
    neighbour_roll = chassis_ctrl.get_attitude(rm_define.chassis_roll)
'''


def closed_course_lab_script(waypoints: list[tuple[float, float]]) -> str:
    """Generate (never execute) a disabled, supervised official-Lab task.

    Points are forward/right metres relative to the initial sample, constrained
    to axis-aligned segments and a total path of at most two metres. No public
    area obstacle avoidance, network control or global localisation is provided.
    Raw odometry units and axis signs still require a physical calibration.
    """
    if type(waypoints) is not list or not 2 <= len(waypoints) <= 17:
        raise ValueError("waypoints")
    points: list[tuple[float, float]] = []
    for point in waypoints:
        if type(point) is not tuple or len(point) != 2:
            raise ValueError("waypoint")
        points.append(tuple(_finite(value, "coordinate", 2) for value in point))
    if points[0] != (0, 0):
        raise ValueError("waypoints_must_start_at_origin")
    distance = 0.0
    for previous, point in pairwise(points):
        dx, dy = point[0] - previous[0], point[1] - previous[1]
        if (abs(dx) > 1e-9) == (abs(dy) > 1e-9):
            raise ValueError("axis_aligned_distinct_segments_required")
        distance += abs(dx) + abs(dy)
    if distance > 2:
        raise ValueError("two_metre_total_path_limit")
    return '''# Neighbour S1 official-Lab CLOSED-COURSE candidate. DO NOT AUTO-RUN.
# Generated offline; no physical S1 movement/stop has been accepted.
# There is NO obstacle detector here: never deploy in occupied/public areas.
# Keep all four switches FALSE until the operator has completed bench acceptance.
MOTION_ENABLED = False
CLOSED_COURSE_CONFIRMED = False
ODOMETRY_UNITS_AND_FRAME_CONFIRMED = False
LOCAL_PHYSICAL_STOP_CONFIRMED = False
# Verify with the read-only kit; do not assume raw odometry is metres.
POSITION_UNITS_PER_METRE = 1.0
FORWARD_SIGN = 1
LATERAL_SIGN = 1
LATERAL_RIGHT_DEGREE = 90
SPEED_MPS = 0.15
POLL_SECONDS = 0.05
MAX_TASK_SECONDS = 20.0
POSITION_TOLERANCE_M = 0.05
HEADING_TOLERANCE_DEG = 3.0
MAX_TILT_DEG = 8.0
NEIGHBOUR_RESULT = 'not_started'
WAYPOINTS = ''' + repr(points) + '''

def neighbour_number(value, bound):
    if type(value) not in (int, float) or value != value or value > bound or value < -bound:
        raise ValueError('invalid_sensor_value')
    return value

def neighbour_pose():
    x = neighbour_number(chassis_ctrl.get_position_based_power_on(rm_define.chassis_forward), 10000)
    y = neighbour_number(chassis_ctrl.get_position_based_power_on(rm_define.chassis_translation), 10000)
    yaw = neighbour_number(chassis_ctrl.get_attitude(rm_define.chassis_yaw), 1000000)
    pitch = neighbour_number(chassis_ctrl.get_attitude(rm_define.chassis_pitch), 180)
    roll = neighbour_number(chassis_ctrl.get_attitude(rm_define.chassis_roll), 180)
    if abs(pitch) > MAX_TILT_DEG or abs(roll) > MAX_TILT_DEG:
        raise ValueError('tilted_chassis')
    return (x * FORWARD_SIGN / POSITION_UNITS_PER_METRE,
            y * LATERAL_SIGN / POSITION_UNITS_PER_METRE, yaw)

def start():
    global NEIGHBOUR_RESULT
    if MOTION_ENABLED is not True:
        NEIGHBOUR_RESULT = 'dry_run_no_hardware_calls'
        return
    if (CLOSED_COURSE_CONFIRMED is not True
            or ODOMETRY_UNITS_AND_FRAME_CONFIRMED is not True
            or LOCAL_PHYSICAL_STOP_CONFIRMED is not True):
        NEIGHBOUR_RESULT = 'bench_acceptance_required'
        return
    try:
        chassis_ctrl.stop()
        if (neighbour_number(POSITION_UNITS_PER_METRE, 10000) <= 0
                or FORWARD_SIGN not in (-1, 1) or LATERAL_SIGN not in (-1, 1)
                or LATERAL_RIGHT_DEGREE not in (-90, 90)):
            raise ValueError('invalid_calibration')
        if (not 0 < neighbour_number(SPEED_MPS, 0.15) <= 0.15
                or not 0.02 <= neighbour_number(POLL_SECONDS, 0.1) <= 0.1
                or not 0 < neighbour_number(MAX_TASK_SECONDS, 20) <= 20
                or not 0 < neighbour_number(POSITION_TOLERANCE_M, 0.05) <= 0.05
                or not 0 < neighbour_number(HEADING_TOLERANCE_DEG, 3) <= 3
                or not 0 < neighbour_number(MAX_TILT_DEG, 8) <= 8):
            raise ValueError('invalid_closed_course_limits')
        initial = neighbour_pose()
        if abs((initial[2] + 180) % 360 - 180) > HEADING_TOLERANCE_DEG:
            raise ValueError('power_on_heading_alignment_required')
        start_time = neighbour_number(tools.run_time_of_program(), 1000000)
        last_time = start_time
        last_pose = initial
        previous_waypoint = WAYPOINTS[0]
        for waypoint in WAYPOINTS[1:]:
            target_x = initial[0] + waypoint[0]
            target_y = initial[1] + waypoint[1]
            x_segment = abs(waypoint[0] - previous_waypoint[0]) > 0.000001
            reached = False
            for tick in range(400):
                time.sleep(POLL_SECONDS)
                now = neighbour_number(tools.run_time_of_program(), 1000000)
                dt = now - last_time
                if dt <= 0 or dt > 0.2 or now - start_time >= MAX_TASK_SECONDS:
                    raise ValueError('timer_stale_or_task_timeout')
                pose = neighbour_pose()
                if (abs(pose[0] - last_pose[0]) + abs(pose[1] - last_pose[1])
                        > 0.04 + 2 * SPEED_MPS * dt):
                    raise ValueError('odometry_jump')
                if abs((pose[2] - initial[2] + 180) % 360 - 180) > HEADING_TOLERANCE_DEG:
                    raise ValueError('heading_changed')
                if chassis_ctrl.is_impact() is not False:
                    raise ValueError('impact_or_invalid_impact_sensor')
                dx, dy = target_x - pose[0], target_y - pose[1]
                if abs(dx) <= POSITION_TOLERANCE_M and abs(dy) <= POSITION_TOLERANCE_M:
                    chassis_ctrl.stop()
                    reached = True
                    break
                if x_segment:
                    if abs(dy) > POSITION_TOLERANCE_M:
                        raise ValueError('cross_track_error')
                    degree = 0 if dx > 0 else 180
                else:
                    if abs(dx) > POSITION_TOLERANCE_M:
                        raise ValueError('cross_track_error')
                    degree = LATERAL_RIGHT_DEGREE if dy > 0 else -LATERAL_RIGHT_DEGREE
                chassis_ctrl.move_degree_with_speed(SPEED_MPS, degree)
                last_time, last_pose = now, pose
            if reached is not True:
                raise ValueError('bounded_loop_exhausted')
            # Sample afresh after each stop; observations cannot be carried over.
            previous_waypoint = waypoint
            last_pose = neighbour_pose()
            last_time = neighbour_number(tools.run_time_of_program(), 1000000)
        NEIGHBOUR_RESULT = 'lab_task_finished_physical_acceptance_required'
    except Exception:
        NEIGHBOUR_RESULT = 'stopped_due_to_error_check_lab'
        raise
    finally:
        chassis_ctrl.stop()
'''


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_field")
        result[key] = value
    return result


def _finite(value: object, name: str, bound: float) -> float:
    if type(value) not in (int, float):
        raise ValueError(name)
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(name) from exc
    if not math.isfinite(result) or abs(result) > bound:
        raise ValueError(name)
    return result


@dataclass(frozen=True)
class LabSnapshot:
    s1_id: str
    boot_id: str
    observed_at: datetime
    uptime_s: float
    forward_raw: float
    translation_raw: float
    rotation_raw: float
    yaw_deg: float
    pitch_deg: float
    roll_deg: float
    live_control_eligible: bool = field(default=False, init=False)
    pose_quality: str = field(default="manual_unverified_power_on_odometry", init=False)


def parse_lab_snapshot(payload: bytes, *, now: datetime) -> LabSnapshot:
    """Validate a human-transcribed snapshot; never use it as live control."""
    if type(payload) is not bytes or not 0 < len(payload) <= MAX_IMPORT_BYTES:
        raise ValueError("payload_size")
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now_timezone")
    try:
        data = json.loads(payload.decode("utf-8"), object_pairs_hook=_pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("payload_json") from exc
    expected = {
        "schema", "source", "s1_id", "boot_id", "observed_at", "uptime_s",
        "forward_raw", "translation_raw", "rotation_raw", "yaw_deg", "pitch_deg", "roll_deg",
    }
    if type(data) is not dict or set(data) != expected:
        raise ValueError("fields")
    if type(data["schema"]) is not int or data["schema"] != 1 or data["source"] != LAB_SOURCE:
        raise ValueError("schema_source")
    for name in ("s1_id", "boot_id"):
        if type(data[name]) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", data[name]):
            raise ValueError(name)
    if type(data["observed_at"]) is not str or len(data["observed_at"]) > 40:
        raise ValueError("observed_at")
    try:
        observed = datetime.fromisoformat(data["observed_at"])
    except ValueError as exc:
        raise ValueError("observed_at") from exc
    if observed.tzinfo is None or observed.utcoffset() is None:
        raise ValueError("observed_at_timezone")
    age = (now - observed).total_seconds()
    if age < 0 or age > 300:
        raise ValueError("observation_stale_or_future")
    values = {
        name: _finite(data[name], name, bound)
        for name, bound in (
            ("uptime_s", 7 * 24 * 3600), ("forward_raw", 10000),
            ("translation_raw", 10000), ("rotation_raw", 1_000_000),
            ("yaw_deg", 1_000_000), ("pitch_deg", 180), ("roll_deg", 180),
        )
    }
    if values["uptime_s"] < 0:
        raise ValueError("uptime_s")
    return LabSnapshot(
        s1_id=data["s1_id"], boot_id=data["boot_id"],
        observed_at=observed.astimezone(UTC), **values,
    )


class LabSnapshotSequence:
    """Reject reused/out-of-order samples; new boot requires a new reader."""

    def __init__(self, *, s1_id: str, boot_id: str) -> None:
        self.s1_id = s1_id
        self.boot_id = boot_id
        self._last: LabSnapshot | None = None

    def accept(self, snapshot: LabSnapshot) -> None:
        if type(snapshot) is not LabSnapshot:
            raise ValueError("snapshot")
        if snapshot.s1_id != self.s1_id or snapshot.boot_id != self.boot_id:
            raise ValueError("device_or_boot_changed")
        if self._last is not None and (
            snapshot.uptime_s <= self._last.uptime_s
            or snapshot.observed_at <= self._last.observed_at
        ):
            raise ValueError("snapshot_not_increasing")
        self._last = snapshot
