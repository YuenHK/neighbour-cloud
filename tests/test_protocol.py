import json

import pytest

from simulator.protocol import Esp32ProtocolSimulator, decode_command, encode_command
from simulator.robot import RobotState


def command(seq: int = 1, command_type: str = "start_patrol") -> dict:
    return {"seq": seq, "type": command_type, "ttl_ms": 500, "mission_id": "demo"}


def test_protocol_accepts_crc_protected_high_level_command() -> None:
    frame = encode_command(command(), sent_ms=1000)

    assert decode_command(frame, now_ms=1200) == command()


def test_protocol_rejects_tampered_crc() -> None:
    frame = encode_command(command(), sent_ms=1000).replace(b"start_patrol", b"cancel_mission")

    with pytest.raises(ValueError, match="CRC mismatch"):
        decode_command(frame, now_ms=1100)


def test_protocol_rejects_direct_motor_control_even_with_valid_crc() -> None:
    unsafe = {**command(), "pwm": 255}

    with pytest.raises(ValueError, match="direct motor control"):
        decode_command(encode_command(unsafe, sent_ms=1000), now_ms=1100)


def test_protocol_rejects_stale_and_duplicate_commands() -> None:
    controller = Esp32ProtocolSimulator()
    frame = encode_command(command(), sent_ms=1000)
    controller.receive(frame, now_ms=1200)

    with pytest.raises(ValueError, match="duplicate"):
        controller.receive(frame, now_ms=1250)
    with pytest.raises(ValueError, match="stale"):
        decode_command(encode_command(command(2), sent_ms=1000), now_ms=1501)


def test_protocol_forces_safe_stop_after_500_ms_without_keepalive() -> None:
    controller = Esp32ProtocolSimulator()
    controller.receive(encode_command(command(), sent_ms=1000), now_ms=1000)
    assert controller.robot.state is RobotState.PATROL

    controller.tick(1500)
    assert controller.robot.state is RobotState.PATROL
    controller.tick(1501)
    assert controller.robot.state is RobotState.SAFE_STOP


def test_invalid_json_is_rejected() -> None:
    with pytest.raises(ValueError, match="invalid JSON"):
        decode_command(json.dumps({"broken": True}).encode()[:-1], now_ms=0)


@pytest.mark.parametrize("field", ["seq", "ttl_ms"])
def test_boolean_is_not_accepted_as_integer(field: str) -> None:
    unsafe = {**command(), field: True}

    with pytest.raises(ValueError, match="invalid"):
        decode_command(encode_command(unsafe, sent_ms=0), now_ms=0)


def test_unknown_envelope_field_is_rejected() -> None:
    envelope = json.loads(encode_command(command(), sent_ms=0))
    envelope["debug_override"] = True

    with pytest.raises(ValueError, match="unknown envelope"):
        decode_command(json.dumps(envelope).encode(), now_ms=0)
