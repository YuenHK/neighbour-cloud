"""Install explicit project adapters in THIS isolated child process only.

Official SDK sources remain pristine. No Robot is created; this loader does
not initialize connections, enumerate adapters, start streams or send commands.
"""
import importlib
import sys

import numpy as np

from ep_runtime import codecs, interfaces


def _h264_decode(self, data):
    # NumPy 2 removed binary fromstring(); retain the SDK's BGR array result.
    result = []
    for raw, width, height, _stride in self._video_decoder.decode(data):
        if len(raw) != width * height * 3:
            raise ValueError('decoder produced invalid frame size')
        result.append(np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3).copy())
    return result


def load_sdk(source):
    if any(name in sys.modules for name in ('robomaster', 'libmedia_codec', 'netifaces')):
        raise RuntimeError('SDK compatibility loading requires a fresh isolated process')
    sys.path.insert(0, str(source))
    sys.modules['libmedia_codec'] = codecs
    sys.modules['netifaces'] = interfaces
    robot = importlib.import_module('robomaster.robot')
    media = importlib.import_module('robomaster.media')
    media.LiveView._h264_decode = _h264_decode
    return robot, media
