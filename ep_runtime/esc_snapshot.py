"""Per-subscription atomic ESC snapshots; fixed DJI sources remain untouched."""
import struct
import time
from dataclasses import dataclass
from types import MethodType


@dataclass(frozen=True)
class EscSnapshot:
    values: tuple | None
    decoded_at: float


def install_snapshot_decoder(subject, clock=time.monotonic):
    def decode(self, buf):
        try:
            fields = struct.unpack('<hhhhhhhhIIIIBBBB', bytes(buf))
            values = tuple(tuple(fields[start:start + 4]) for start in (0, 4, 8, 12))
        except (ValueError, TypeError, struct.error):
            values = None
        # One reference assignment publishes a whole immutable frame. Native DDS
        # may decode another frame before its asynchronous callback executes.
        self._console_frame = EscSnapshot(values, clock())

    subject._console_frame = EscSnapshot(None, clock())
    subject.decode = MethodType(decode, subject)
    subject.data_info = MethodType(lambda self: self._console_frame, subject)
    return subject


def subscribe_snapshot_esc(robot, callback):
    from robomaster.chassis import EscSubject
    subject = install_snapshot_decoder(EscSubject())
    subject.freq = 10
    return robot.dds.add_subject_info(subject, callback, (), {})
