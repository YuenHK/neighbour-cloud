"""Run with the EP venv: python -m unittest ep_runtime.tests; no devices."""
import socket
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import av
import numpy as np

from ep_runtime import interfaces
from ep_runtime.codecs import H264Decoder, OpusDecoder


class CodecTests(unittest.TestCase):
    def test_bad_h264_input_is_bounded(self):
        decoder = H264Decoder()
        for value in (None, 'bytes', b'x' * 1_000_001):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                decoder.decode(value)
        with self.assertRaises(ValueError):
            H264Decoder(output_format='RGB')

    def test_h264_parser_without_frames_has_an_accumulation_budget(self):
        decoder = H264Decoder()
        for _ in range(4):
            decoder.decode(b'x' * 1_000_000)
        with self.assertRaises(ValueError):
            decoder.decode(b'x')

    def test_opus_defaults_and_packet_limits(self):
        for options in ({'channels': 2}, {'sample_rate': 16000}, {'frame_size': True}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                OpusDecoder(**options)
        decoder = OpusDecoder()
        for value in (None, b'', b'x' * 1276):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ValueError):
                decoder.decode(value)

    def test_synthetic_nonzero_opus_decodes_pcm16_mono(self):
        encoder = av.CodecContext.create('libopus', 'w')
        encoder.sample_rate, encoder.layout, encoder.format = 48000, 'mono', 's16'
        samples = (np.sin(np.arange(960) * 2 * np.pi * 440 / 48000) * 8000).astype(np.int16)
        frame = av.AudioFrame.from_ndarray(samples[None, :], format='s16', layout='mono')
        frame.sample_rate = 48000
        packets = list(encoder.encode(frame)) + list(encoder.encode(None))
        decoder = OpusDecoder()
        outputs = [decoder.decode(bytes(packet)) for packet in packets]
        self.assertTrue(all(len(output) == 1920 for output in outputs))
        self.assertGreater(int(np.abs(np.frombuffer(b''.join(outputs), dtype='<i2').astype(int)).max()), 100)

    def test_ifaddr_adapter_matches_ipv4_surface_without_real_enumeration(self):
        adapter = SimpleNamespace(name='test-adapter', ips=[
            SimpleNamespace(ip='192.0.2.10', network_prefix=24),
            SimpleNamespace(ip=('::1', 0, 0), network_prefix=128)])
        with patch.object(interfaces.ifaddr, 'get_adapters', return_value=[adapter]):
            self.assertEqual(interfaces.interfaces(), ['test-adapter'])
            self.assertEqual(interfaces.ifaddresses('test-adapter'), {
                socket.AF_INET: [{'addr': '192.0.2.10', 'netmask': '255.255.255.0'}]})
            with self.assertRaises(ValueError):
                interfaces.ifaddresses('unknown')


if __name__ == '__main__':
    unittest.main()
