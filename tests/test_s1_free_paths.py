import ast
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from random import Random
from types import SimpleNamespace

import pytest

from edge_hub.s1_lab import (
    LabSnapshotSequence,
    closed_course_lab_script,
    parse_lab_snapshot,
    readonly_lab_script,
)
from edge_hub.s1_sbus import (
    CENTRE,
    BenchEvidence,
    MobilityCommand,
    S1SBusBench,
    SBusFrame,
    decode_frame,
    encode_frame,
    route_capabilities,
)
from tools.s1_offline_kit import create_kit

NOW = datetime(2026, 11, 5, 4, 0, tzinfo=UTC)


def bench_ready():
    # Synthetic evidence only. Never an assertion about the user's S1.
    return BenchEvidence(True, True, True, True, True)


def command(**updates):
    return replace(MobilityCommand(1, 1000, 1250, forward=0.1), **updates)


def snapshot(**updates):
    value = {
        "schema": 1, "source": "dji-s1-lab-manual", "s1_id": "synthetic-s1",
        "boot_id": "synthetic-boot", "observed_at": NOW.isoformat(), "uptime_s": 20,
        "forward_raw": 1.2, "translation_raw": -0.3, "rotation_raw": 90,
        "yaw_deg": 90, "pitch_deg": 0.1, "roll_deg": -0.1,
    }
    return json.dumps({**value, **updates}).encode()


def test_codec_known_zero_maximum_and_one_hot_vectors():
    assert encode_frame(SBusFrame((0,) * 16)) == b"\x0f" + b"\0" * 24
    assert encode_frame(SBusFrame((2047,) * 16))[1:23] == b"\xff" * 22
    # Known boundary across byte and channel boundaries, independent of decoder.
    channels = [0] * 16
    channels[0], channels[1], channels[15] = 1, 1, 1024
    packet = encode_frame(SBusFrame(tuple(channels)))
    assert packet[1:4] == bytes((1, 8, 0)) and packet[22] == 128


def test_codec_seeded_roundtrips_and_only_standard_flags():
    rng = Random(44571)
    for _ in range(500):
        value = SBusFrame(tuple(rng.randint(0, 2047) for _ in range(16)),
                         bool(rng.getrandbits(1)), bool(rng.getrandbits(1)))
        assert decode_frame(encode_frame(value)) == value
    assert encode_frame(SBusFrame((1024,) * 16, True, True))[23] == 0x0C


@pytest.mark.parametrize("channels", [(1024,) * 15, (1024,) * 17,
                                      (True,) * 16, (-1,) * 16, (2048,) * 16,
                                      [1024] * 16])
def test_codec_rejects_invalid_channels(channels):
    with pytest.raises(ValueError):
        SBusFrame(channels)


@pytest.mark.parametrize("change", ["header", "footer", "ch17", "reserved", "short", "type"])
def test_decoder_rejects_corruption_and_unsupported_digital_channels(change):
    packet = bytearray(encode_frame(SBusFrame((1024,) * 16)))
    if change == "header":
        packet[0] = 0
    elif change == "footer":
        packet[24] = 4
    elif change == "ch17":
        packet[23] = 1
    elif change == "reserved":
        packet[23] = 0x80
    elif change == "short":
        packet.pop()
    with pytest.raises(ValueError):
        decode_frame(packet if change == "type" else bytes(packet))


def test_default_cannot_activate_and_preview_cannot_enable_transport():
    bench = S1SBusBench()
    assert len(bench.evidence.missing()) == 5
    with pytest.raises(ValueError, match="bench_evidence_required"):
        bench.submit(command(), now_ms=1000)
    preview = bench.tick(now_ms=1100)
    assert not preview.active and not preview.transport_enabled
    assert decode_frame(preview.packet).failsafe
    assert route_capabilities()["serial_transport_implemented"] is False
    assert route_capabilities()["camera_or_telemetry_return_channel"] is False


@pytest.mark.parametrize("missing", ["firmware_verified", "electrical_levels_verified",
                                    "inversion_and_100k_8e2_verified",
                                    "channels_and_polarities_verified", "physical_stop_verified"])
def test_each_missing_physical_gate_independently_prevents_active_preview(missing):
    bench = S1SBusBench(replace(bench_ready(), **{missing: False}))
    with pytest.raises(ValueError, match="bench_evidence_required"):
        bench.submit(command(), now_ms=1000)
    assert not bench.tick(now_ms=1001).active


def test_truthy_evidence_and_invalid_clock_cannot_keep_command_active():
    with pytest.raises(ValueError, match="evidence_must_be_boolean"):
        BenchEvidence(firmware_verified="true")
    bench = S1SBusBench(bench_ready())
    bench.submit(command(), now_ms=1000)
    with pytest.raises(ValueError, match="clock"):
        bench.tick(now_ms=True)
    assert not bench.tick(now_ms=1001).active


def test_mobility_uses_documented_free_mode_channels_only_and_never_releases():
    bench = S1SBusBench(bench_ready())
    bench.submit(command(lateral=-0.2, yaw=0.2), now_ms=1000)
    preview = bench.tick(now_ms=1001)
    value = decode_frame(preview.packet)
    assert preview.active and not preview.transport_enabled
    assert value.channels[:4] == (890, 1091, 1024, 1158)
    assert value.channels[4:7] == (924, 924, 1124)
    assert value.channels[7:] == (1024,) * 9
    assert not value.failsafe and not value.frame_lost


def test_expiry_and_release_stop_frame_are_latched_without_resuming_old_commands():
    bench = S1SBusBench(bench_ready())
    bench.submit(command(), now_ms=1000)
    assert bench.tick(now_ms=1249).active
    preview = bench.tick(now_ms=1250)
    assert not preview.active and preview.reason == "command_expired"
    value = decode_frame(preview.packet)
    assert value.channels[:4] == (CENTRE,) * 4 and value.failsafe and value.frame_lost
    assert value.channels[6] == 1124  # No automatic chassis torque Release.
    assert not bench.tick(now_ms=2000).active


def test_operator_stop_and_clock_reversal_revoke_preview():
    bench = S1SBusBench(bench_ready())
    bench.submit(command(), now_ms=1000)
    bench.stop()
    assert not bench.tick(now_ms=1001).active
    bench.submit(command(sequence=2, created_ms=1001, expires_ms=1200), now_ms=1001)
    with pytest.raises(ValueError, match="clock_reversed"):
        bench.tick(now_ms=900)
    assert not bench.tick(now_ms=1002).active


@pytest.mark.parametrize("updates", [
    {"sequence": True}, {"sequence": 1}, {"created_ms": 1001},
    {"expires_ms": 1000}, {"expires_ms": 1251}, {"forward": 0.21},
    {"lateral": float("nan")}, {"yaw": float("inf")}, {"forward": True},
    {"yaw": 10**1000},
])
def test_rejected_or_replayed_command_revokes_existing_preview(updates):
    bench = S1SBusBench(bench_ready())
    bench.submit(command(), now_ms=1000)
    bad = command(sequence=2)
    bad = replace(bad, **updates)
    with pytest.raises(ValueError):
        bench.submit(bad, now_ms=1000)
    assert not bench.tick(now_ms=1000).active


def test_lab_template_executes_only_documented_getters_against_fake_apis():
    script = readonly_lab_script()
    tree = ast.parse(script)
    calls = [ast.unparse(node.func) for node in ast.walk(tree) if isinstance(node, ast.Call)]
    assert calls == ["tools.get_unixtime"] + ["chassis_ctrl.get_position_based_power_on"] * 3 + [
        "chassis_ctrl.get_attitude"] * 3
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom, ast.While))
                   for node in ast.walk(tree))
    read_calls = []

    def read_position(axis):
        read_calls.append(("position", axis))
        return [1.5, -0.5, 45][axis]

    def read_attitude(axis):
        read_calls.append(("attitude", axis))
        return [45, 0.1, -0.1][axis - 3]

    namespace = {
        "__builtins__": {},
        "tools": SimpleNamespace(get_unixtime=lambda: 123),
        "chassis_ctrl": SimpleNamespace(get_position_based_power_on=read_position,
                                        get_attitude=read_attitude),
        "rm_define": SimpleNamespace(chassis_forward=0, chassis_translation=1, chassis_rotate=2,
                                      chassis_yaw=3, chassis_pitch=4, chassis_roll=5),
    }
    exec(compile(tree, "synthetic-s1-lab", "exec"), namespace)  # noqa: S102 - fixed local template
    assert read_calls == []  # Importing/generating a template never polls hardware.
    namespace["start"]()
    assert read_calls == [("position", 0), ("position", 1), ("position", 2),
                          ("attitude", 3), ("attitude", 4), ("attitude", 5)]
    assert namespace["neighbour_uptime"] == 123
    assert namespace["neighbour_forward"] == 1.5


def test_manual_snapshot_never_claims_live_control_or_surveyed_pose():
    value = parse_lab_snapshot(snapshot(), now=NOW)
    assert value.forward_raw == 1.2 and not value.live_control_eligible
    assert value.pose_quality == "manual_unverified_power_on_odometry"


@pytest.mark.parametrize("updates", [
    {"schema": True}, {"source": "sdk"}, {"s1_id": "../../real"}, {"boot_id": ""},
    {"observed_at": "2026-11-05T04:00:00"},
    {"observed_at": (NOW + timedelta(seconds=1)).isoformat()},
    {"observed_at": (NOW - timedelta(seconds=301)).isoformat()},
    {"uptime_s": -1}, {"yaw_deg": float("nan")}, {"roll_deg": 181},
    {"forward_raw": True}, {"translation_raw": 10**1000}, {"extra": "no"},
])
def test_manual_snapshot_invalid_or_stale_input_rejected(updates):
    with pytest.raises(ValueError):
        parse_lab_snapshot(snapshot(**updates), now=NOW)


def test_manual_snapshot_duplicate_unknown_oversize_and_bad_json_rejected():
    for payload in (snapshot()[:-1] + b',"schema":1}', b"{" + b" " * 4096, b"[]", b"\xff"):
        with pytest.raises(ValueError):
            parse_lab_snapshot(payload, now=NOW)


def test_manual_snapshot_sequence_requires_same_device_boot_and_increasing_time():
    first = parse_lab_snapshot(snapshot(), now=NOW)
    reader = LabSnapshotSequence(s1_id=first.s1_id, boot_id=first.boot_id)
    reader.accept(first)
    with pytest.raises(ValueError, match="snapshot_not_increasing"):
        reader.accept(first)
    for changes in ({"boot_id": "new-boot"}, {"s1_id": "other-s1"}):
        value = parse_lab_snapshot(snapshot(**changes), now=NOW)
        with pytest.raises(ValueError, match="device_or_boot_changed"):
            reader.accept(value)
    second = parse_lab_snapshot(snapshot(uptime_s=21, observed_at=(NOW + timedelta(seconds=1)).isoformat()),
                                now=NOW + timedelta(seconds=1))
    reader.accept(second)


def test_offline_kit_writes_only_template_metadata_and_never_overwrites(tmp_path):
    paths = create_kit(tmp_path / "synthetic-kit")
    assert {path.name for path in paths} == {"s1-lab-readonly.py", "capabilities.json",
                                            "s1-lab-closed-course-DISABLED.py"}
    assert paths[0].read_text(encoding="utf-8") == readonly_lab_script()
    capabilities = json.loads((tmp_path / "synthetic-kit" / "capabilities.json").read_text())
    assert capabilities["hardware_verified"] is False
    assert capabilities["autonomous_hardware_driving"] is False
    before = {path.name: path.read_bytes() for path in paths}
    with pytest.raises(ValueError, match="refuse_to_overwrite_existing_kit"):
        create_kit(tmp_path / "synthetic-kit")
    assert {path.name: path.read_bytes() for path in paths} == before


class FakeLab:
    """Deterministic simulated S1; has no socket/serial/SDK/actual-time methods."""

    def __init__(self, *, failure=None):
        self.elapsed = 1.0
        self.x, self.y = 0.0, 0.0
        self.vx, self.vy = 0.0, 0.0
        self.stops, self.moves = 0, []
        self.failure = failure
        self.calls = []

    def sleep(self, seconds):
        self.calls.append("sleep")
        if self.failure == "stale_timer":
            return
        self.elapsed += seconds
        if self.failure != "no_progress":
            self.x += self.vx * seconds
            self.y += self.vy * seconds

    def get_position_based_power_on(self, axis):
        self.calls.append("position")
        if self.failure == "sensor_exception" and self.moves:
            raise RuntimeError("synthetic_read_failure")
        if self.failure == "nan_position" and self.moves:
            return float("nan")
        if self.failure == "jump" and self.moves:
            return 5.0
        return self.x if axis == 0 else self.y

    def get_attitude(self, axis):
        self.calls.append("attitude")
        if axis == 3 and self.failure == "misaligned":
            return 90
        if axis == 3 and self.failure == "heading" and self.moves:
            return 10
        if axis == 4 and self.failure == "tilt" and self.moves:
            return 10
        return 0.0

    def is_impact(self):
        self.calls.append("impact")
        return bool(self.failure == "impact" and self.moves)

    def move_degree_with_speed(self, speed, degree):
        self.calls.append("move")
        self.moves.append((speed, degree))
        self.vx = speed if degree == 0 else (-speed if degree == 180 else 0.0)
        self.vy = speed if degree == 90 else (-speed if degree == -90 else 0.0)

    def stop(self):
        self.calls.append("stop")
        self.stops += 1
        self.vx, self.vy = 0.0, 0.0

    def namespace(self, *, enabled=False, points=None):
        script = closed_course_lab_script(points or [(0.0, 0.0), (0.3, 0.0)])
        namespace = {
            "__builtins__": {"range": range, "abs": abs, "ValueError": ValueError,
                             "Exception": Exception, "type": type, "int": int, "float": float},
            "chassis_ctrl": self,
            "time": self,
            "tools": SimpleNamespace(run_time_of_program=lambda: self.elapsed),
            "rm_define": SimpleNamespace(chassis_forward=0, chassis_translation=1, chassis_rotate=2,
                                          chassis_yaw=3, chassis_pitch=4, chassis_roll=5),
        }
        exec(script, namespace)  # noqa: S102 - locally generated fixed bounded template
        if enabled:
            for flag in ("MOTION_ENABLED", "CLOSED_COURSE_CONFIRMED",
                         "ODOMETRY_UNITS_AND_FRAME_CONFIRMED", "LOCAL_PHYSICAL_STOP_CONFIRMED"):
                namespace[flag] = True
        return namespace


def test_closed_course_default_is_dry_run_without_even_a_stop_or_sensor_call():
    robot = FakeLab()
    namespace = robot.namespace()
    namespace["start"]()
    assert namespace["NEIGHBOUR_RESULT"] == "dry_run_no_hardware_calls"
    assert robot.calls == []


@pytest.mark.parametrize("missing", ["CLOSED_COURSE_CONFIRMED",
                                    "ODOMETRY_UNITS_AND_FRAME_CONFIRMED",
                                    "LOCAL_PHYSICAL_STOP_CONFIRMED"])
def test_closed_course_each_missing_gate_rejects_without_hardware_calls(missing):
    robot = FakeLab()
    namespace = robot.namespace(enabled=True)
    namespace[missing] = False
    namespace["start"]()
    assert namespace["NEIGHBOUR_RESULT"] == "bench_acceptance_required"
    assert robot.calls == []


def test_closed_course_fake_lab_completes_positive_lateral_and_reverse_segments_stopping():
    robot = FakeLab()
    points = [(0.0, 0.0), (0.2, 0.0), (0.2, 0.2), (0.0, 0.2), (0.0, 0.0)]
    namespace = robot.namespace(enabled=True, points=points)
    namespace["start"]()
    assert {degree for _, degree in robot.moves} == {0, 90, 180, -90}
    assert all(speed == 0.15 for speed, _ in robot.moves)
    assert abs(robot.x) <= 0.05 and abs(robot.y) <= 0.05
    assert robot.calls[-1] == "stop" and robot.vx == robot.vy == 0
    assert namespace["NEIGHBOUR_RESULT"] == "lab_task_finished_physical_acceptance_required"


@pytest.mark.parametrize("failure", ["sensor_exception", "nan_position", "jump", "heading",
                                    "tilt", "impact", "stale_timer", "no_progress", "misaligned"])
def test_closed_course_fake_lab_sensor_or_timer_failure_always_stops(failure):
    robot = FakeLab(failure=failure)
    namespace = robot.namespace(enabled=True)
    with pytest.raises((ValueError, RuntimeError)):
        namespace["start"]()
    assert namespace["NEIGHBOUR_RESULT"] == "stopped_due_to_error_check_lab"
    assert robot.calls[-1] == "stop" and robot.vx == robot.vy == 0
    assert len(robot.moves) <= 400


@pytest.mark.parametrize("settings", [
    {"POSITION_UNITS_PER_METRE": 0}, {"POSITION_UNITS_PER_METRE": float("nan")},
    {"FORWARD_SIGN": 0}, {"LATERAL_RIGHT_DEGREE": 0}, {"SPEED_MPS": 0.16},
    {"MAX_TASK_SECONDS": 21}, {"POLL_SECONDS": 1}, {"POSITION_TOLERANCE_M": 1},
])
def test_closed_course_bad_calibration_or_relaxed_limits_cannot_start_moving(settings):
    robot = FakeLab()
    namespace = robot.namespace(enabled=True)
    namespace.update(settings)
    with pytest.raises(ValueError):
        namespace["start"]()
    assert not robot.moves and robot.calls[-1] == "stop"


@pytest.mark.parametrize("points", [
    [], [(0, 0)], [(1, 1), (1, 2)], [(0, 0), (0.1, 0.1)],
    [(0, 0), (0, 0)], [(0, 0), (2.1, 0)], [(0, 0), (1, 0), (1, 1), (0, 1)],
    [(0, 0), (True, 0)], [(0, 0), (float("nan"), 0)],
])
def test_closed_course_generator_rejects_unbounded_or_non_axis_aligned_routes(points):
    with pytest.raises(ValueError):
        closed_course_lab_script(points)
