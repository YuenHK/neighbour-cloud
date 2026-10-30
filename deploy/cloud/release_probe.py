"""One explicit free release acceptance run, never a periodic provider poll.

Only fixed public cake conversation and a fixed HiuMaan phrase are sent.
Generated audio is held in memory for Whisper, never played or microphone
captured. A durable attempt is written before dispatch; a restart cannot repeat
an uncertain/failed attempt. Existing quota guards/reservations stay in force.
"""
import asyncio
import base64
import io
import json
import re
import sqlite3
import time
import wave
from array import array
from contextlib import closing

import httpx
from fastapi import HTTPException

from deploy.cloud.transcription_api import MODEL, Transcription, ready, wav_data
from edge_hub import azure_voice, cloudflare_gemma
from edge_hub.resident_cloud import CloudUnavailable
from edge_hub.resident_inference import RESIDENT_LOCAL_PROMPT
from edge_hub.resident_models import GEMMA_MODEL

PHRASE = '你好，今日見到你真係好開心。你可以慢慢同我傾。'
QUESTIONS = ('我今日整咗香蕉蛋糕。', '阿媽幫我一齊整。', '頭先提過邊個幫我整？')


class ReleaseProbeError(RuntimeError):
    pass


class ProbeStore:
    def __init__(self, db, *, initialize=False):
        self.db = db
        exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='cloud_release_probes'").fetchone()
        if not exists:
            if initialize is not True or db.in_transaction:
                raise ReleaseProbeError('explicit_release_probe_store_required')
            with db:
                db.execute('CREATE TABLE cloud_release_probes(release_sha256 TEXT PRIMARY KEY,state TEXT NOT NULL,'
                           'started_ms INTEGER NOT NULL,finished_ms INTEGER,summary TEXT NOT NULL)')
        fields = [row[1] for row in db.execute('PRAGMA table_info(cloud_release_probes)')]
        if fields != ['release_sha256', 'state', 'started_ms', 'finished_ms', 'summary']:
            raise ReleaseProbeError('release_probe_schema_requires_review')

    def begin(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{64}', identity) or self.db.in_transaction:
            raise ReleaseProbeError('release_probe_identity_required')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT state,summary FROM cloud_release_probes WHERE release_sha256=?', (identity,)).fetchone()
            if row:
                if row[0] == 'passed':
                    result = json.loads(row[1])
                    if not isinstance(result, dict) or result.get('gemma_route') != 'gemma-cloudflare-free' or result.get('voice') != azure_voice.VOICE:
                        raise ReleaseProbeError('release_probe_receipt_invalid')
                    return result
                raise ReleaseProbeError('release_probe_already_attempted_review_before_retry')
            self.db.execute('INSERT INTO cloud_release_probes VALUES(?,?,?,NULL,?)',
                            (identity, 'pending', int(time.time() * 1000), '{}'))
        return None

    def finish(self, identity, state, summary):
        if state not in ('passed', 'failed') or not isinstance(summary, dict) or len(json.dumps(summary)) > 8192 or self.db.in_transaction:
            raise ReleaseProbeError('release_probe_receipt_invalid')
        with self.db:
            self.db.execute('BEGIN IMMEDIATE')
            row = self.db.execute('SELECT state FROM cloud_release_probes WHERE release_sha256=?', (identity,)).fetchone()
            if row is None or row[0] != 'pending':
                raise ReleaseProbeError('release_probe_attempt_changed')
            self.db.execute('UPDATE cloud_release_probes SET state=?,finished_ms=?,summary=? WHERE release_sha256=?',
                            (state, int(time.time() * 1000), json.dumps(summary, sort_keys=True), identity))


def public_audio():
    start, first, pcm = time.monotonic(), None, bytearray()
    chunks = azure_voice.pcm_chunks(PHRASE)
    try:
        for chunk in chunks:
            if first is None:
                first = round((time.monotonic() - start) * 1000)
            pcm.extend(chunk)
            if len(pcm) > 45 * 48000:
                raise ReleaseProbeError('release_probe_audio_budget')
    finally:
        chunks.close()
    if not pcm or len(pcm) % 2:
        raise ReleaseProbeError('release_probe_audio_missing')
    # Fixed 24k -> 16k conversion for this synthetic probe, no extra binary/GPU.
    # The actual browser already records its input at 16k.
    samples = array('h')
    samples.frombytes(bytes(pcm))
    converted = array('h')
    for index in range(0, len(samples) - 2, 3):
        converted.extend((samples[index], (samples[index + 1] + samples[index + 2]) // 2))
    output = io.BytesIO()
    with wave.open(output, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(16000)
        stream.writeframes(converted.tobytes())
    audio = output.getvalue()
    wav_data(base64.b64encode(audio).decode())
    return audio, {'voice_first_bytes_ms': first, 'voice_complete_ms': round((time.monotonic() - start) * 1000),
                   'pcm_bytes': len(pcm), 'voice': azure_voice.VOICE}


class ReleaseProbe:
    def __init__(self, services, backup_connect, identity):
        self.services, self.connect, self.identity = services, backup_connect, identity

    async def __call__(self):
        def begin():
            with closing(self.connect()) as db:
                return ProbeStore(db).begin(self.identity)

        def finish(state, summary):
            with closing(self.connect()) as db:
                ProbeStore(db).finish(self.identity, state, summary)

        previous = await asyncio.to_thread(begin)
        if previous is not None:
            return previous  # Cold boot/heartbeat consumes no provider quota.
        phase = 'gemma'
        try:
            with self.services.scope():
                times, history = [], []
                async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
                    for text in QUESTIONS:
                        phase = f'gemma_round_{len(times) + 1}'
                        history.append({'role': 'user', 'content': text})
                        start = time.monotonic()
                        response = await cloudflare_gemma.complete({'messages': history, 'stream': False},
                            prompt=RESIDENT_LOCAL_PROMPT, client=client)
                        body = json.loads(response.body)
                        answer = body['choices'][0]['message']['content']
                        if (not isinstance(answer, str) or not answer.strip() or body.get('model') != GEMMA_MODEL
                                or response.headers.get('x-resident-route') != 'gemma-cloudflare-free'):
                            raise ReleaseProbeError('release_probe_fixed_gemma_unconfirmed')
                        history.append({'role': 'assistant', 'content': answer})
                        times.append(round((time.monotonic() - start) * 1000))
                    if not any(value in answer for value in ('媽', '妈', '母親', '母亲')):
                        raise ReleaseProbeError('release_probe_context_unconfirmed')
                    phase = 'voice'
                    audio, voice = await asyncio.to_thread(public_audio)
                    phase = 'whisper'
                    info, root = ready()
                    engine = Transcription(lambda: client)
                    start = time.monotonic()
                    try:
                        result = await engine.dispatch(audio, info, root)
                    finally:
                        await engine.close()
                    if result.get('engine') != 'cloudflare-whisper-free' or result.get('model') != MODEL or not result.get('text', '').strip():
                        raise ReleaseProbeError('release_probe_whisper_unconfirmed')
                    summary = {'gemma_route': 'gemma-cloudflare-free', 'gemma_ms': times, 'context_carried': True,
                               **voice, 'whisper_ms': round((time.monotonic() - start) * 1000),
                               'whisper_model': MODEL, 'whisper_engine': result['engine'],
                               'microphone_used': False, 'audio_played': False, 'sample_scope': 'fixed_public_synthetic_only'}
            await asyncio.to_thread(finish, 'passed', summary)
            return summary
        except (HTTPException, CloudUnavailable, httpx.HTTPError, OSError, ValueError, RuntimeError, sqlite3.Error, KeyError, TypeError) as error:
            try:
                failure = {'error_type': type(error).__name__, 'phase': phase}
                if isinstance(error, HTTPException):
                    failure['http_status'] = error.status_code
                elif isinstance(error, httpx.HTTPStatusError):
                    failure['http_status'] = error.response.status_code
                if phase.startswith('gemma'):
                    failure['gemma_failure'] = cloudflare_gemma.state().get('last_failure_detail')
                await asyncio.to_thread(finish, 'failed', failure)
            except (OSError, ValueError, RuntimeError, sqlite3.Error):
                pass  # A durable pending attempt still prevents automatic replay.
            raise ReleaseProbeError('release_provider_acceptance_requires_review') from None
