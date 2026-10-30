import asyncio
import json
import sqlite3
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fastapi.responses import JSONResponse

from deploy.cloud import release_probe
from deploy.cloud.backup_store import BackupStore
from deploy.cloud.release_probe import ProbeStore, ReleaseProbe, ReleaseProbeError
from edge_hub.resident_models import GEMMA_MODEL


@pytest.fixture
def probe(tmp_path, monkeypatch):
    database = tmp_path / 'durable-operations.sqlite3'
    with sqlite3.connect(database) as db:
        BackupStore(db, b'PUBLIC-SYNTHETIC-KEY-ONLY-' + b'x' * 16, initialize=True)
        ProbeStore(db, initialize=True)
    calls = {'gemma': [], 'voice': [], 'whisper': []}

    async def complete(payload, **kwargs):
        calls['gemma'].append(json.loads(json.dumps(payload)))
        return JSONResponse({'model': GEMMA_MODEL, 'choices': [{'message': {'content': '阿媽幫你整蛋糕，好窩心呀。'}}]},
                            headers={'X-Resident-Route': 'gemma-cloudflare-free'})

    def chunks(text):
        calls['voice'].append(text)
        yield b'\x00\x01' * 12000

    async def transcribe(self, raw, info, root):
        calls['whisper'].append({'bytes': len(raw), 'info': info, 'root': root})
        return {'text': '你好，今日見到你真係好開心。', 'engine': 'cloudflare-whisper-free', 'model': release_probe.MODEL}

    monkeypatch.setattr(release_probe.cloudflare_gemma, 'complete', complete)
    monkeypatch.setattr(release_probe.azure_voice, 'pcm_chunks', chunks)
    monkeypatch.setattr(release_probe, 'ready', lambda: ({'account_id': 'a' * 32}, tmp_path))
    monkeypatch.setattr(release_probe.Transcription, 'dispatch', transcribe)
    services = SimpleNamespace(scope=nullcontext)
    instance = ReleaseProbe(services, lambda: sqlite3.connect(database), 'b' * 64)
    return instance, database, calls


def test_fixed_three_round_context_azure_pcm_and_whisper_only_once_across_restarts(probe):
    instance, database, calls = probe
    result = asyncio.run(instance())
    assert result['context_carried'] and result['voice'] == 'zh-HK-HiuMaanNeural'
    assert not result['microphone_used'] and not result['audio_played']
    assert result['sample_scope'] == 'fixed_public_synthetic_only'
    assert [len(item['messages']) for item in calls['gemma']] == [1, 3, 5]
    assert calls['voice'] == [release_probe.PHRASE] and len(calls['whisper']) == 1
    assert calls['whisper'][0]['bytes'] == 44 + 16000  # 0.5 sec 16k 16-bit mono WAV.
    again = ReleaseProbe(instance.services, instance.connect, instance.identity)
    assert asyncio.run(again()) == result
    assert len(calls['gemma']) == 3 and len(calls['voice']) == len(calls['whisper']) == 1
    with sqlite3.connect(database) as db:
        row = db.execute('SELECT state,summary FROM cloud_release_probes').fetchone()
        assert row[0] == 'passed' and '阿媽' not in row[1]  # No generated transcript/reply content persisted.
        BackupStore(db, b'PUBLIC-SYNTHETIC-KEY-ONLY-' + b'x' * 16)


def test_voice_failure_is_durable_no_local_fallback_no_automatic_retry(probe, monkeypatch):
    instance, database, calls = probe

    def broken_voice(_text):
        raise ValueError('SYNTHETIC-PRIVATE-SECRET-MUST-NOT-BE-LOGGED')

    monkeypatch.setattr(release_probe.azure_voice, 'pcm_chunks', broken_voice)
    with pytest.raises(ReleaseProbeError, match='requires_review'):
        asyncio.run(instance())
    with sqlite3.connect(database) as db:
        state, summary = db.execute('SELECT state,summary FROM cloud_release_probes').fetchone()
        assert state == 'failed' and json.loads(summary)['phase'] == 'voice'
        assert 'SECRET' not in summary
    with pytest.raises(ReleaseProbeError, match='already_attempted'):
        asyncio.run(instance())
    assert len(calls['gemma']) == 3 and calls['whisper'] == [] and calls['voice'] == []


def test_missing_operational_store_is_not_automatically_recreated_or_charged(probe, tmp_path):
    instance, _, calls = probe
    absent = tmp_path / 'empty.sqlite3'
    empty = ReleaseProbe(instance.services, lambda: sqlite3.connect(absent), instance.identity)
    with pytest.raises(ReleaseProbeError, match='explicit_release_probe_store_required'):
        asyncio.run(empty())
    assert calls == {'gemma': [], 'voice': [], 'whisper': []}
    with sqlite3.connect(absent) as db:
        assert db.execute('SELECT 1 FROM sqlite_master').fetchone() is None


def test_unknown_previous_attempt_is_never_replayed(probe):
    instance, database, calls = probe
    with sqlite3.connect(database) as db:
        assert ProbeStore(db).begin(instance.identity) is None
    with pytest.raises(ReleaseProbeError, match='already_attempted'):
        asyncio.run(instance())
    assert calls == {'gemma': [], 'voice': [], 'whisper': []}


def test_gemma_wrong_context_does_not_proceed_to_voice_or_asr(probe, monkeypatch):
    instance, _, calls = probe

    async def wrong_context(*args, **kwargs):
        return JSONResponse({'model': GEMMA_MODEL, 'choices': [{'message': {'content': '我唔記得邊個。'}}]},
                            headers={'X-Resident-Route': 'gemma-cloudflare-free'})

    monkeypatch.setattr(release_probe.cloudflare_gemma, 'complete', wrong_context)
    with pytest.raises(ReleaseProbeError):
        asyncio.run(instance())
    assert calls['voice'] == calls['whisper'] == []
