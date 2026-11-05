"""S1's documented S-Bus route, with a memory-only acceptance harness.

This module deliberately has no serial, socket, SDK, device-discovery or firmware
code. Bytes returned here are bench previews, never evidence that a robot moved
or stopped. DJI's S1 manual v1.8, pp. 48--49 documents the input and channels.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

FRAME_SIZE = 25
CENTRE = 1024
STICK_SPAN = 672
MAX_PREVIEW_DEFLECTION = 0.2
MAX_COMMAND_AGE_MS = 250
DOCUMENTED_MINIMUM_FIRMWARE = "00.05.0046"
MANUAL_URL = (
    "https://dl.djicdn.com/downloads/robomaster-s1/20220429UM/"
    "RoboMaster_S1_User_Manual_v1.8_EN.pdf"
)


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(name)
    return value


def _finite(value: object, name: str) -> float:
    if type(value) not in (int, float):
        raise ValueError(name)
    try:
        result = float(value)
    except OverflowError as exc:
        raise ValueError(name) from exc
    if not math.isfinite(result):
        raise ValueError(name)
    return result


@dataclass(frozen=True)
class SBusFrame:
    channels: tuple[int, ...]
    frame_lost: bool = False
    failsafe: bool = False

    def __post_init__(self) -> None:
        if type(self.channels) is not tuple or len(self.channels) != 16:
            raise ValueError("channels")
        for channel in self.channels:
            _integer(channel, "channel", 0, 2047)
        if type(self.frame_lost) is not bool or type(self.failsafe) is not bool:
            raise ValueError("flags")


def encode_frame(frame: SBusFrame) -> bytes:
    """Pack the sixteen 11-bit channels; no I/O and no digital CH17/18."""
    if type(frame) is not SBusFrame:
        raise ValueError("frame")
    payload = sum(channel << (11 * i) for i, channel in enumerate(frame.channels))
    flags = (4 if frame.frame_lost else 0) | (8 if frame.failsafe else 0)
    return b"\x0f" + payload.to_bytes(22, "little") + bytes((flags, 0))


def decode_frame(packet: bytes) -> SBusFrame:
    """Strict standard S-Bus v1 decoding; reject unknown/digital flag bits."""
    if type(packet) is not bytes or len(packet) != FRAME_SIZE:
        raise ValueError("packet_length")
    if packet[0] != 0x0F or packet[-1] != 0 or packet[23] & ~0x0C:
        raise ValueError("packet_format")
    payload = int.from_bytes(packet[1:23], "little")
    channels = tuple((payload >> (11 * i)) & 0x7FF for i in range(16))
    return SBusFrame(channels, bool(packet[23] & 4), bool(packet[23] & 8))


@dataclass(frozen=True)
class BenchEvidence:
    """A harness gate, NOT a hardware licence or automatic robot activation.

    Values must originate in a supervised bench record before a future real
    adapter can be considered. There is no real adapter in this module.
    """

    firmware_verified: bool = False
    electrical_levels_verified: bool = False
    inversion_and_100k_8e2_verified: bool = False
    channels_and_polarities_verified: bool = False
    physical_stop_verified: bool = False

    def __post_init__(self) -> None:
        for value in self.__dict__.values():
            if type(value) is not bool:
                raise ValueError("evidence_must_be_boolean")

    def missing(self) -> tuple[str, ...]:
        fields = (
            "firmware_verified", "electrical_levels_verified",
            "inversion_and_100k_8e2_verified", "channels_and_polarities_verified",
            "physical_stop_verified",
        )
        return tuple(name for name in fields if getattr(self, name) is not True)


@dataclass(frozen=True)
class MobilityCommand:
    sequence: int
    created_ms: int
    expires_ms: int
    lateral: float = 0.0
    forward: float = 0.0
    yaw: float = 0.0


@dataclass(frozen=True)
class BenchPreview:
    packet: bytes
    reason: str
    active: bool
    transport_enabled: bool = False


def _idle_channels() -> tuple[int, ...]:
    channels = [CENTRE] * 16
    # Manual's offsets: slow speed, Free mode, torque Set. Never Release.
    # Actual acceptance of these levels is part of the unmet physical gate.
    channels[4] = CENTRE - 100
    channels[5] = CENTRE - 100
    channels[6] = CENTRE + 100
    return tuple(channels)


class S1SBusBench:
    """Deterministic, memory-only watchdog and S1 mobility packet compiler.

    Call tick from a fake clock in tests. Production does not import this into
    an EP worker, and this class cannot open or write a device. A real bridge
    would additionally require an independent microcontroller watchdog: host
    process failure cannot be made safe by this Python clock alone.
    """

    def __init__(self, evidence: BenchEvidence | None = None) -> None:
        if evidence is not None and type(evidence) is not BenchEvidence:
            raise ValueError("bench_evidence")
        self.evidence = evidence or BenchEvidence()
        self._command: MobilityCommand | None = None
        self._sequence = -1
        self._last_ms: int | None = None
        self._reason = "not_activated"

    def _clock(self, now_ms: int) -> None:
        try:
            _integer(now_ms, "clock", 0, 2**63 - 1)
        except ValueError:
            self._command = None
            self._reason = "clock_invalid"
            raise
        if self._last_ms is not None and now_ms < self._last_ms:
            self._command = None
            self._reason = "clock_reversed"
            raise ValueError("clock_reversed")
        self._last_ms = now_ms

    def submit(self, command: MobilityCommand, *, now_ms: int) -> None:
        """Only permit an attended simulated command after all bench gates."""
        self._clock(now_ms)
        try:
            if self.evidence.missing():
                raise ValueError("bench_evidence_required")
            if type(command) is not MobilityCommand:
                raise ValueError("command")
            _integer(command.sequence, "sequence", 0, 2**53 - 1)
            _integer(command.created_ms, "created_ms", 0, 2**63 - 1)
            _integer(command.expires_ms, "expires_ms", 0, 2**63 - 1)
            if command.sequence <= self._sequence:
                raise ValueError("sequence_not_increasing")
            if not command.created_ms <= now_ms < command.expires_ms:
                raise ValueError("command_expired_or_future")
            if not 0 < command.expires_ms - command.created_ms <= MAX_COMMAND_AGE_MS:
                raise ValueError("command_lifetime")
            for name in ("lateral", "forward", "yaw"):
                value = _finite(getattr(command, name), name)
                if abs(value) > MAX_PREVIEW_DEFLECTION:
                    raise ValueError("deflection_limit")
            self._command = command
            self._sequence = command.sequence
            self._reason = "simulated_command"
        except ValueError:
            self._command = None
            self._reason = "rejected_command"
            raise

    def stop(self) -> None:
        """Revoke the preview; no actuator call or chassis Release is made."""
        self._command = None
        self._reason = "operator_stop"

    def tick(self, *, now_ms: int) -> BenchPreview:
        self._clock(now_ms)
        command = self._command
        if command is not None and now_ms >= command.expires_ms:
            self._command = None
            self._reason = "command_expired"
            command = None
        channels = list(_idle_channels())
        active = command is not None and not self.evidence.missing()
        if active:
            # Free mode: CH1 lateral, CH2 longitudinal, CH4 chassis yaw.
            for index, value in ((0, command.lateral), (1, command.forward), (3, command.yaw)):
                channels[index] = CENTRE + round(value * STICK_SPAN)
        frame = SBusFrame(tuple(channels), frame_lost=not active, failsafe=not active)
        return BenchPreview(encode_frame(frame), self._reason, active)


def route_capabilities() -> dict[str, object]:
    """Honest static capability envelope for callers/reviewers."""
    return {
        "model": "s1", "route": "official_sbus_candidate",
        "official_route_documented": True, "minimum_firmware": DOCUMENTED_MINIMUM_FIRMWARE,
        "manual_url": MANUAL_URL, "manual_pages": [48, 49],
        "serial_transport_implemented": False, "hardware_verified": False,
        "camera_or_telemetry_return_channel": False, "remote_sdk_verified": False,
        "autonomous_hardware_driving": False, "weapons_channel_implemented": False,
        "requires": list(BenchEvidence().missing()),
    }
