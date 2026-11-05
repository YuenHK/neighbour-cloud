"""Atomic raw body telemetry; no stateful SDK cs=0 position transformation."""
import struct
import time
from dataclasses import dataclass
from types import MethodType


@dataclass(frozen=True)
class BodySnapshot:
    topic: str
    values: tuple | None
    decoded_at: float
    serial: int


def install_body_decoder(subject, topic, clock=time.monotonic):
    fmt = '<ffffff' if topic == 'velocity' else '<fff'
    subject._console_serial = 0
    subject._console_frame = BodySnapshot(topic, None, clock(), 0)

    def decode(self, buf):
        try:
            values = struct.unpack(fmt, bytes(buf))
        except (struct.error, TypeError, ValueError):
            values = None
        self._console_serial += 1
        self._console_frame = BodySnapshot(topic, values, clock(), self._console_serial)

    subject.decode = MethodType(decode, subject)
    subject.data_info = MethodType(lambda self: self._console_frame, subject)
    return subject


def subscribe_body_snapshots(robot, callback):
    from robomaster.chassis import AttiInfoSubject, PositionSubject, VelocitySubject
    # Power-on/world coordinates. Never use the SDK's mutating cs=0 data_info.
    subjects = [('position', PositionSubject(cs=1)), ('attitude', AttiInfoSubject()),
                ('velocity', VelocitySubject())]
    for topic, subject in subjects:
        install_body_decoder(subject, topic)
        subject.freq = 10
        if robot.dds.add_subject_info(subject, callback, (), {}) is not True:
            return False
    return True
