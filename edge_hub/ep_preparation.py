"""Offline EP contracts only: no SDK import, sockets, device I/O or file writes."""
from __future__ import annotations

import io
import math
import struct
import threading
import time
import wave

import numpy as np


def preparation_status(sdk_report=None, *, adapted_runtime_state='not_checked'):
    known = {'blocked_native_wheel_abi', 'blocked_python_requirement',
             'invalid_python_requirement', 'artifact_checksum_review_required',
             'dependency_review_required', 'unsupported_python_implementation'}
    reported = sdk_report.get('status') if isinstance(sdk_report, dict) else None
    state = reported if isinstance(reported, str) and reported in known else 'not_verified'
    adapted = adapted_runtime_state if isinstance(adapted_runtime_state, str) and adapted_runtime_state in {
        'not_checked', 'unavailable', 'incompatible_or_stale', 'reported_offline_pass'
    } else 'not_checked'
    return {
        'schema': 'ep-offline-preparation-v1', 'target_model': 'EP',
        'scope': 'offline_preparation_not_hardware_acceptance',
        'connection': 'not_connected', 'autonomous_navigation': False,
        'motion_enabled': False, 'video_enabled': False, 'audio_enabled': False,
        'hardware_acceptance': False, 'sdk_report_state': state,
        'sdk_import_verified': False,
        'sdk_import_scope': 'edge_hub_does_not_import_sdk',
        'adapted_runtime_report_state': adapted,
        'adapted_runtime_evidence_scope': 'mutable_local_report_and_source_hashes_not_live_attestation',
        'sdk_timeout_scope': 'host_timer_not_hardware_watchdog',
        'connection_plan': {
            'mode': 'sta_router', 'state': 'planned_not_configured',
            'pc_link': 'ethernet_to_same_router_preferred',
            'ep_link': 'wifi_to_same_router_pending_firmware_review',
            'firmware_state': 'awaiting_user_information',
            'network_configuration_applied': False, 'discovery_enabled': False,
            'router_credentials_stored': False, 'public_exposure_enabled': False,
            'remote_admin_access': 'not_configured_loopback_only',
        },
        'control': {'mode': 'manual_hold_to_run_planned', 'command_ttl_max_ms': 500,
                    'linear_speed_limit_mps': .15, 'yaw_speed_limit_dps': 15},
        'video': {'strategy': 'newest', 'inbox_capacity': 1, 'max_age_ms': 500,
                  'privacy_gate': 'not_accepted', 'raw_persistence': False},
        'speech': {'tts_target': 'mono_pcm16_wav_48000hz', 'max_chunk_seconds': 10,
                   'microphone_capture': False, 'playback_verified': False},
        'pending_gates': ['sdk_runtime', 'firmware_and_link', 'physical_stop',
                          'pc_and_network_failure_stop', 'manual_takeover',
                          'video_privacy_and_latency', 'audio_consent_and_echo'],
    }


def prepare_ep_tts_wav(payload: bytes) -> bytes:
    """Convert generated TTS only; not a recorder/player or speech-quality acceptance.

    Source is bounded mono PCM16 at supported rates <=48 kHz. Upsampling uses
    linear interpolation; actual robot playback quality/latency remains untested.
    """
    if type(payload) is not bytes or not 44 <= len(payload) <= 1_000_000:
        raise ValueError('invalid EP speech input')
    try:
        with wave.open(io.BytesIO(payload), 'rb') as audio:
            rate, frames = audio.getframerate(), audio.getnframes()
            if (audio.getnchannels() != 1 or audio.getsampwidth() != 2
                    or audio.getcomptype() != 'NONE' or rate not in (16000, 22050, 24000, 48000)
                    or not 0 < frames <= rate * 10):
                raise ValueError('invalid EP speech format')
            raw = audio.readframes(frames)
            if len(raw) != frames * 2:
                raise ValueError('truncated EP speech input')
    except (wave.Error, EOFError, struct.error) as error:
        raise ValueError('invalid EP speech input') from error
    if rate != 48000:
        samples = np.frombuffer(raw, dtype='<i2')
        count = round(frames * 48000 / rate)
        positions = np.arange(count, dtype=np.float64) * rate / 48000
        converted = np.interp(positions, np.arange(frames), samples)
        raw = np.clip(np.rint(converted), -32768, 32767).astype('<i2').tobytes()
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(48000)
        audio.writeframes(raw)
    return output.getvalue()


class EpVideoInbox:
    """Single-slot raw RAM inbox for a future trusted capture -> privacy pipeline.

    Not an HTTP preview, privacy filter or camera reader. Nothing is captured,
    encoded, displayed or persisted here. Consuming a frame does not authorize
    its release: approved privacy processing must happen downstream.
    """
    def __init__(self, *, clock=time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._frame = None
        self._received_at = None

    def put(self, frame):
        with self._lock:
            self._frame = self._received_at = None
            if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
                    or frame.ndim != 3 or frame.shape[2] != 3
                    or not 0 < frame.shape[0] <= 720 or not 0 < frame.shape[1] <= 1280):
                raise ValueError('invalid EP video frame')
            now = self._clock()
            if not math.isfinite(now):
                raise ValueError('invalid EP video clock')
            self._frame, self._received_at = frame.copy(), now

    def take_for_privacy(self):
        with self._lock:
            frame, received = self._frame, self._received_at
            self._frame = self._received_at = None
            if frame is None:
                return None
            age = self._clock() - received
            return frame if math.isfinite(age) and 0 <= age <= .5 else None
