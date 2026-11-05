"""Project adaptation of DJI's decoder API using a CPython 3.12 PyAV wheel.

This is not DJI's original libmedia_codec binary. No sockets, capture or playback.
"""
import struct

import av


class H264Decoder:
    def __init__(self, output_format='BGR', verbose=False):
        if output_format != 'BGR':
            raise ValueError('only BGR is supported')
        self._context = av.CodecContext.create('h264', 'r')
        self._context.thread_count = 2
        self._pending_bytes = 0

    def decode(self, data):
        if type(data) is not bytes or len(data) > 1_000_000:
            raise ValueError('invalid H264 packet')
        self._pending_bytes += len(data)
        if self._pending_bytes > 4_000_000:
            raise ValueError('H264 parser buffer budget exceeded; recreate decoder')
        frames = []
        for packet in self._context.parse(data):
            frames.extend(self._context.decode(packet))
        if not data:
            frames.extend(self._context.decode(None))
        if len(frames) > 64:
            raise ValueError('too many H264 frames')
        result = []
        for frame in frames:
            if not 0 < frame.width <= 1280 or not 0 < frame.height <= 720:
                raise ValueError('unsupported EP frame dimensions')
            raw = frame.to_ndarray(format='bgr24').tobytes()
            result.append((raw, frame.width, frame.height, frame.width * 3))
        if result:
            self._pending_bytes = 0
        return result


class OpusDecoder:
    def __init__(self, frame_size=960, sample_rate=48000, channels=1):
        if (type(frame_size) is not int or frame_size != 960
                or type(sample_rate) is not int or sample_rate != 48000
                or type(channels) is not int or channels != 1):
            raise ValueError('only the SDK mono 48 kHz/960-sample default is supported')
        self._context = av.CodecContext.create('opus', 'r')
        self._context.extradata = b'OpusHead' + struct.pack('<BBHIhB', 1, 1, 0, 48000, 0, 0)
        self._resampler = av.AudioResampler(format='s16', layout='mono', rate=48000)

    def decode(self, data):
        if type(data) is not bytes or not 0 < len(data) <= 1275:
            raise ValueError('invalid Opus packet')
        result = []
        count = 0
        for decoded in self._context.decode(av.Packet(data)):
            for frame in self._resampler.resample(decoded):
                count += frame.samples
                if count > 960:
                    raise ValueError('Opus packet exceeds SDK 20 ms frame contract')
                result.append(frame.to_ndarray().astype('<i2', copy=False).tobytes())
        return b''.join(result)
