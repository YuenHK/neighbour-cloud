"""Run with the audio venv: python -m unittest local_audio_gateway.test_service -v."""
import asyncio
import json
import subprocess
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from local_audio_gateway import app as service


class SpeechServiceTests(unittest.TestCase):
    def test_azure_pause_precedes_cache_and_no_fallback(self):
        request = service.SpeechRequest(model='azure-hiumaan-f0', voice='zh-HK-HiuMaanNeural', input='Azure公開測試')
        wav = service.wav_bytes(np.zeros(160), 16000)
        with patch.object(service.azure_voice, 'require_available'), \
                patch.object(service.azure_voice, 'synthesize', return_value=wav) as azure, \
                patch.object(service.mimo_voice, 'synthesize') as mimo:
            response = service.speech(request)
            self.assertEqual(response.headers['x-tts-engine'], 'azure-hiumaan-f0')
            with patch.object(service.azure_voice, 'require_available', side_effect=ValueError('paused')):
                with self.assertRaises(service.HTTPException) as raised:
                    service.speech(request)
            self.assertEqual(raised.exception.status_code, 503)
            azure.assert_called_once()
            mimo.assert_not_called()

    def test_mimo_bingtang_uses_cloud_and_never_google_or_local(self):
        wav = service.wav_bytes(np.zeros(160), 16000)
        with patch.object(service.mimo_voice, 'synthesize', return_value=wav) as cloud, \
                patch.object(service.gemini_voice, 'synthesize') as google, patch.object(service, 'get_tts') as local:
            response = service.speech(service.SpeechRequest(model='mimo-v2.5-tts', voice='冰糖', input='本次MiMo合成測試'))
            self.assertEqual(response.headers['x-tts-engine'], 'mimo-cantonese-bingtang')
            self.assertEqual(service.health()['tts_last_resident']['requested_voice'], '冰糖')
            with self.assertRaises(service.HTTPException):
                service.speech(service.SpeechRequest(model='mimo-v2.5-tts', voice='HKSoft', input='拒絕錯誤聲線'))
            cloud.assert_called_once()
            google.assert_not_called()
            local.assert_not_called()
        with patch.object(service.mimo_voice, 'synthesize', side_effect=ValueError('offline')), \
                patch.object(service, 'get_tts') as local:
            with self.assertRaises(service.HTTPException) as raised:
                service.speech(service.SpeechRequest(model='mimo-v2.5-tts', voice='冰糖', input='另一項失敗測試'))
            self.assertEqual(raised.exception.status_code, 503)
            local.assert_not_called()

    def test_airi_google_model_alias_uses_hksoft_and_rejects_other_voices_without_local_fallback(self):
        profile = {'name': 'original', 'pace': 1, 'tts_provider': 'gemini', 'gemini_voice': 'HKSoft'}
        wav = service.wav_bytes(np.zeros(160), 16000)
        with patch.object(service, 'voice_profile', return_value=profile), \
                patch.object(service, '_gemini_cooldown_until', 0), \
                patch.object(service.gemini_voice, 'synthesize', return_value=wav) as cloud, \
                patch.object(service, 'get_tts') as local:
            response = service.speech(service.SpeechRequest(model='google-hksoft-tts', voice='HKSoft', input='公開聲線測試'))
            self.assertEqual(response.headers['x-tts-engine'], 'gemini-cantonese-hksoft')
            self.assertEqual(service.health()['tts_last_resident']['requested_voice'], 'HKSoft')
            with self.assertRaises(service.HTTPException) as raised:
                service.speech(service.SpeechRequest(model='google-hksoft-tts', voice='alloy', input='公開測試'))
            self.assertEqual(raised.exception.status_code, 400)
            cloud.assert_called_once()
            local.assert_not_called()

    def test_provider_connection_pools_are_reused_and_closed_without_synthesis(self):
        stt = SimpleNamespace(aclose=AsyncMock())
        tts = SimpleNamespace(close=Mock())
        async def lifecycle():
            with patch.object(service.httpx, 'AsyncClient', return_value=stt), \
                    patch.object(service.httpx, 'Client', return_value=tts), \
                    patch.object(service.gemini_voice, 'synthesize') as synthesize:
                await service.open_stt_connection()
                self.assertIs(service.app.state.tts_client, tts)
                await service.close_stt_connection()
                synthesize.assert_not_called()
        asyncio.run(lifecycle())
        stt.aclose.assert_awaited_once()
        tts.close.assert_called_once()
        del service.app.state.tts_client
        del service.app.state.stt_client

    def test_hk_prosody_revision_does_not_replay_old_cached_audio(self):
        profile = {'name': 'original', 'pace': 1, 'tts_provider': 'gemini', 'gemini_voice': 'HKSoft'}
        data = service.wav_bytes(np.zeros(160), 16000)
        with patch.object(service, 'voice_profile', return_value=profile), \
                patch.object(service, '_gemini_cooldown_until', 0), \
                patch.object(service.gemini_voice, 'synthesize', return_value=data) as cloud:
            with patch.object(service.gemini_voice, 'HK_STYLE_REVISION', 'synthetic-v1'):
                service.speech(service.SpeechRequest(input='公開同一句', voice='resident-yue'))
                cached = service.speech(service.SpeechRequest(input='公開同一句', voice='resident-yue'))
                self.assertEqual(cached.headers['x-tts-cache'], 'hit')
            with patch.object(service.gemini_voice, 'HK_STYLE_REVISION', 'synthetic-v2'):
                revised = service.speech(service.SpeechRequest(input='公開同一句', voice='resident-yue'))
                self.assertEqual(revised.headers['x-tts-cache'], 'miss')
            self.assertEqual(cloud.call_count, 2)

    def test_selected_gemini_voice_is_cached_and_local_warmup_never_calls_cloud(self):
        profile = {'name': 'original', 'pace': 1, 'tts_provider': 'gemini', 'gemini_voice': 'Leda'}
        data = service.wav_bytes(np.zeros(160), 16000)
        local = SimpleNamespace(generate=Mock(return_value=SimpleNamespace(samples=np.zeros(160), sample_rate=16000)))
        with patch.object(service, 'voice_profile', return_value=profile), \
                patch.object(service, '_gemini_cooldown_until', 0), \
                patch.object(service.gemini_voice, 'synthesize', return_value=data) as cloud, \
                patch.object(service, 'get_tts', return_value=local):
            first = service.speech(service.SpeechRequest(input='你好', voice='resident-yue'))
            self.assertEqual(first.headers['x-tts-engine'], 'gemini-cantonese-leda')
            lock = threading.Lock()
            lock.acquire()
            try:
                with patch.object(service, '_tts_generation_lock', lock):
                    cached = service.speech(service.SpeechRequest(input='你好', voice='resident-yue'))
                    self.assertEqual(cached.headers['x-tts-cache'], 'hit')
            finally:
                lock.release()
            service.speech(service.SpeechRequest(input='你好', voice='local-yue'))
            self.assertEqual(cloud.call_count, 1)
            self.assertEqual(service.health()['tts_last_resident']['engine'], 'gemini-cantonese-leda')
            self.assertEqual(service.health()['tts_last']['requested_voice'], 'local-yue')

    def test_resident_quota_error_never_uses_local_voice_or_retries(self):
        import httpx
        profile = {'name': 'original', 'pace': 1, 'tts_provider': 'gemini', 'gemini_voice': 'Leda'}
        failure = httpx.HTTPStatusError('synthetic quota', request=httpx.Request('POST', 'https://example.org'), response=httpx.Response(429))
        local = SimpleNamespace(generate=Mock(return_value=SimpleNamespace(samples=np.zeros(160), sample_rate=16000)))
        with patch.object(service, 'voice_profile', return_value=profile), \
                patch.object(service, '_gemini_cooldown_until', 0), \
                patch.object(service.gemini_voice, 'synthesize', side_effect=failure) as cloud, \
                patch.object(service, 'get_tts', return_value=local):
            for text in ('你好', '好'):
                with self.assertRaises(service.HTTPException) as raised:
                    service.speech(service.SpeechRequest(input=text, voice='resident-yue'))
                self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(cloud.call_count, 1)
            local.generate.assert_not_called()
            diagnostic = service.health()['tts_cloud_last_error']
            self.assertEqual(diagnostic['http_status'], 429)
            self.assertEqual(diagnostic['reason'], 'rate_limited')
            self.assertNotIn('synthetic quota', json.dumps(diagnostic))

    def test_operator_studio_voice_stays_local_with_resident_cloud_voice_selected(self):
        profile = {'name': 'original', 'pace': 1, 'tts_provider': 'gemini', 'gemini_voice': 'Leda'}
        local = SimpleNamespace(generate=Mock(return_value=SimpleNamespace(samples=np.zeros(160), sample_rate=16000)))
        with patch.object(service, 'voice_profile', return_value=profile), \
                patch.object(service.gemini_voice, 'synthesize') as cloud, \
                patch.object(service, 'get_tts', return_value=local):
            result = service.speech(service.SpeechRequest(input='你好', voice='yue'))
            self.assertEqual(result.headers['x-tts-engine'], 'vits-cantonese')
            cloud.assert_not_called()

    def test_resident_voice_never_enters_local_engine_with_an_old_local_setting(self):
        with patch.object(service, 'voice_profile', return_value={'name': 'original', 'tts_provider': 'local'}), \
                patch.object(service, 'get_tts') as local, \
                self.assertRaises(service.HTTPException) as raised:
            service.speech(service.SpeechRequest(input='公開測試', voice='resident-yue'))
        self.assertEqual(raised.exception.status_code, 503)
        local.assert_not_called()

    def test_local_profile_avoids_cloud_and_keeps_cantonese_negation(self):
        upload = SimpleNamespace(read=AsyncMock(return_value=b'synthetic-audio'))
        with patch.object(service, 'voice_profile', return_value={'stt_provider': 'local'}), \
                patch.object(service, 'siliconflow_enabled', return_value=True), \
                patch.object(service, 'decode_audio', return_value=np.zeros(1600, dtype=np.float32)), \
                patch.object(service, 'recognize_local', return_value='唔好通知管理处'), \
                patch.object(service.siliconflow, 'transcribe', new=AsyncMock()) as cloud:
            response = asyncio.run(service._transcribe_audio(upload, 'json'))
        self.assertEqual(json.loads(response.body)['text'], '唔好通知管理處')
        cloud.assert_not_called()

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.fallback = self.root / 'mock-espeak'
        self.fallback.touch()
        (self.root / 'lexicon.txt').write_text('請 \n请 ts\n你 n\n好 h\n', encoding='utf-8')
        self.root_patch = patch.object(service, 'TTS_MODEL_ROOT', self.root)
        self.root_patch.start()
        self.availability_patch = patch.object(service, 'stt_availability', service.SttAvailability())
        self.availability_patch.start()
        service._tts_cache.clear()

    def tearDown(self):
        service._tts_cache.clear()
        self.root_patch.stop()
        self.availability_patch.stop()
        self.folder.cleanup()

    def test_busy_stt_request_rejected_before_read_decode_or_cloud(self):
        async def check():
            capacity = threading.BoundedSemaphore(2)
            capacity.acquire()
            capacity.acquire()
            upload = SimpleNamespace(read=AsyncMock())
            with patch.object(service, '_stt_request_slots', capacity, create=True), \
                    patch.object(service, 'decode_audio') as decode, \
                    patch.object(service.siliconflow, 'transcribe') as cloud, \
                    self.assertRaises(service.HTTPException) as raised:
                await service.transcribe(upload)
            self.assertEqual(raised.exception.status_code, 503)
            self.assertEqual(raised.exception.headers['Retry-After'], '1')
            upload.read.assert_not_awaited()
            decode.assert_not_called()
            cloud.assert_not_called()
            capacity.release()
            capacity.release()  # rejecting caller must not release another caller's slot
        asyncio.run(check())

    def test_cloud_stt_outage_does_not_reupload_and_reports_degraded_state(self):
        async def check():
            samples = np.zeros(160, dtype=np.float32)
            cloud = AsyncMock(side_effect=service.HTTPException(503, 'mock network failure'))
            with patch.object(service, 'decode_audio', return_value=samples), \
                    patch.object(service, 'siliconflow_enabled', return_value=True), \
                    patch.object(service.siliconflow, 'transcribe', cloud):
                for _ in range(2):
                    upload = SimpleNamespace(read=AsyncMock(return_value=b'synthetic-fixture'))
                    with self.assertRaises(service.HTTPException):
                        await service.transcribe(upload)
                self.assertEqual(cloud.await_count, 1)
                snapshot = service.health()['stt_availability']
                self.assertEqual(snapshot['last_result'], 'upstream_unavailable')
                self.assertFalse(snapshot['automatic_retries'])
        asyncio.run(check())

    def test_stt_admission_released_after_success_or_exception(self):
        async def check():
            for failure in (None, service.HTTPException(400, 'mock')):
                with self.subTest(failure=bool(failure)):
                    capacity = threading.BoundedSemaphore(1)
                    worker = AsyncMock(side_effect=failure) if failure else AsyncMock(
                        side_effect=[np.zeros(160, dtype=np.float32), 'mock-transcript'])
                    upload = SimpleNamespace(read=AsyncMock(return_value=b'mock'))
                    with patch.object(service, '_stt_request_slots', capacity, create=True), \
                            patch.object(service, 'run_in_threadpool', worker), \
                            patch.object(service, 'siliconflow_enabled', return_value=False):
                        if failure:
                            with self.assertRaises(service.HTTPException):
                                await service.transcribe(upload)
                        else:
                            result = await service.transcribe(upload)
                            self.assertEqual(json.loads(result.body)['text'], 'mock-transcript')
                    self.assertTrue(capacity.acquire(blocking=False))
                    capacity.release()
        asyncio.run(check())

    def test_stt_admission_held_during_cloud_wait_and_released_on_cancel(self):
        async def check():
            capacity = threading.BoundedSemaphore(1)
            entered = asyncio.Event()
            async def wait_for_cloud(*args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
            upload = SimpleNamespace(read=AsyncMock(return_value=b'mock'))
            with patch.object(service, '_stt_request_slots', capacity, create=True), \
                    patch.object(service, 'run_in_threadpool', AsyncMock(
                        return_value=np.zeros(160, dtype=np.float32))), \
                    patch.object(service, 'siliconflow_enabled', return_value=True), \
                    patch.object(service.siliconflow, 'transcribe', side_effect=wait_for_cloud):
                task = asyncio.create_task(service.transcribe(upload))
                await asyncio.wait_for(entered.wait(), timeout=1)
                acquired = capacity.acquire(blocking=False)
                if acquired:
                    capacity.release()
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(acquired)
            self.assertTrue(capacity.acquire(blocking=False))
            capacity.release()
        asyncio.run(check())

    def test_http_stt_busy_is_retryable_and_does_not_block_cached_tts(self):
        capacity = threading.BoundedSemaphore(1)
        capacity.acquire()
        client = TestClient(service.app)
        service.cache_speech(('你好', 1.0), b'RIFFmock', 'vits-cantonese')
        with patch.object(service, '_stt_request_slots', capacity), \
                patch.object(service, 'decode_audio') as decode, \
                patch.object(service, 'get_tts') as tts:
            response = client.post('/v1/audio/transcriptions',
                                   files={'file': ('mock.wav', b'mock', 'audio/wav')})
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Retry-After'], '1')
            self.assertEqual(client.post('/v1/audio/speech',
                                         json={'input': '你好'}).status_code, 200)
            self.assertEqual(client.get('/health').status_code, 200)
        decode.assert_not_called()
        tts.assert_not_called()
        capacity.release()

    def test_decoded_audio_limit_rejects_overlong_pcm_not_just_file_bytes(self):
        with patch.object(service, '_MAX_STT_SAMPLES', 320, create=True):
            accepted = service.decode_audio(service.wav_bytes(np.zeros(320), 16000))
            self.assertEqual(accepted.shape, (320,))
            with self.assertRaises(service.HTTPException) as raised:
                service.decode_audio(service.wav_bytes(np.zeros(321), 16000))
        self.assertEqual(raised.exception.status_code, 413)

    def test_decoder_stops_before_reading_more_frames_after_limit(self):
        converted = Mock()
        converted.to_ndarray.return_value = np.zeros((1, 321), dtype=np.float32)
        def frames(**kwargs):
            yield object()
            self.fail('decoder continued after decoded sample limit')
        container = Mock()
        container.decode.side_effect = frames
        context = Mock()
        context.__enter__ = Mock(return_value=container)
        context.__exit__ = Mock(return_value=False)
        resampler = Mock()
        resampler.resample.return_value = [converted]
        with patch.object(service.av, 'open', return_value=context), \
                patch.object(service.av, 'AudioResampler', return_value=resampler), \
                patch.object(service, '_MAX_STT_SAMPLES', 320, create=True), \
                self.assertRaises(service.HTTPException) as raised:
            service.decode_audio(b'mock-compressed-audio')
        self.assertEqual(raised.exception.status_code, 413)
        context.__exit__.assert_called_once()

    def test_resampler_flush_is_bounded_and_nonfinite_audio_rejected(self):
        for samples, status in ((np.zeros((1, 321)), 413),
                                (np.array([[float('nan')]]), 400)):
            with self.subTest(status=status):
                container = Mock()
                container.decode.return_value = []
                context = Mock()
                context.__enter__ = Mock(return_value=container)
                context.__exit__ = Mock(return_value=False)
                converted = Mock()
                converted.to_ndarray.return_value = samples
                resampler = Mock()
                resampler.resample.return_value = [converted]
                with patch.object(service.av, 'open', return_value=context), \
                        patch.object(service.av, 'AudioResampler', return_value=resampler), \
                        patch.object(service, '_MAX_STT_SAMPLES', 320, create=True), \
                        self.assertRaises(service.HTTPException) as raised:
                    service.decode_audio(b'mock-audio')
                self.assertEqual(raised.exception.status_code, status)

    def test_invalid_audio_error_does_not_echo_decoder_details(self):
        with patch.object(service.av, 'open', side_effect=ValueError('private-path-and-content')), \
                self.assertRaises(service.HTTPException) as raised:
            service.decode_audio(b'private-data')
        self.assertEqual(raised.exception.status_code, 400)
        self.assertNotIn('private', raised.exception.detail)

    def test_sample_budget_is_cumulative_including_flush_and_ignores_empty_frames(self):
        for final_size, status in ((160, None), (161, 413)):
            with self.subTest(final_size=final_size):
                container = Mock()
                container.decode.return_value = [object()]
                context = Mock()
                context.__enter__ = Mock(return_value=container)
                context.__exit__ = Mock(return_value=False)
                def converted(count):
                    frame = Mock()
                    frame.to_ndarray.return_value = np.zeros((1, count), dtype=np.float32)
                    return frame
                resampler = Mock()
                resampler.resample.side_effect = [[converted(0), converted(160)],
                                                  [converted(final_size)]]
                with patch.object(service.av, 'open', return_value=context), \
                        patch.object(service.av, 'AudioResampler', return_value=resampler), \
                        patch.object(service, '_MAX_STT_SAMPLES', 320):
                    if status:
                        with self.assertRaises(service.HTTPException) as raised:
                            service.decode_audio(b'mock')
                        self.assertEqual(raised.exception.status_code, status)
                    else:
                        self.assertEqual(service.decode_audio(b'mock').shape, (320,))

    def test_overlong_http_audio_never_enters_cloud_or_local_recognition(self):
        client = TestClient(service.app)
        with patch.object(service, '_MAX_STT_SAMPLES', 320, create=True), \
                patch.object(service.siliconflow, 'transcribe') as cloud, \
                patch.object(service, 'recognize_local') as local:
            response = client.post('/v1/audio/transcriptions',
                                   files={'file': ('synthetic.wav',
                                          service.wav_bytes(np.zeros(321), 16000), 'audio/wav')})
        self.assertEqual(response.status_code, 413)
        cloud.assert_not_called()
        local.assert_not_called()

    def test_traditional_text_is_voiced_and_cached_in_memory(self):
        engine = Mock()
        engine.generate.return_value = SimpleNamespace(samples=np.zeros(160), sample_rate=16000)
        with patch.object(service, 'get_tts', return_value=engine):
            first = service.speech(service.SpeechRequest(input='請你好'))
            second = service.speech(service.SpeechRequest(input='請你好'))
        engine.generate.assert_called_once_with('请你好', sid=0, speed=1.0)
        self.assertEqual(first.headers['x-tts-engine'], 'vits-cantonese')
        self.assertEqual(first.headers['x-tts-cache'], 'miss')
        self.assertEqual(second.headers['x-tts-cache'], 'hit')
        self.assertTrue(first.body.startswith(b'RIFF'))

    def test_unsupported_text_never_silently_enters_vits(self):
        with (
            patch.object(service, 'get_tts') as engine,
            patch.object(service, 'ESPEAK', self.root / 'missing.exe'),
            self.assertRaises(service.HTTPException) as raised,
        ):
            service.speech(service.SpeechRequest(input='龘'))
        self.assertEqual(raised.exception.status_code, 503)
        engine.assert_not_called()

    def test_cache_has_a_strict_entry_bound(self):
        for i in range(50):
            service.cache_speech((str(i), 1.0), b'bytes', 'test')
        self.assertEqual(len(service._tts_cache), 32)
        self.assertNotIn(('0', 1.0), service._tts_cache)

    def test_cached_speech_does_not_wait_for_other_synthesis(self):
        service.cache_speech(('你好', 1.0), b'RIFFtest', 'vits-cantonese')
        with ThreadPoolExecutor(max_workers=1) as pool:
            service._tts_generation_lock.acquire()
            try:
                result = pool.submit(service.speech, service.SpeechRequest(input='你好')).result(timeout=1)
                self.assertEqual(result.headers['x-tts-cache'], 'hit')
            finally:
                service._tts_generation_lock.release()

    def test_startup_preloads_only_fixed_reviewed_intro(self):
        self.assertEqual(service.FAST_INTRO,
                         ('你好，今日有咩幫到你？', '有咩需要，慢慢同我講就得。', '好，我幫你跟進。'))
        with patch.object(service, 'get_tts') as engine, patch.object(service, 'speech') as synthesize:
            service.warm_cantonese_tts()
        engine.return_value.generate.assert_called_once_with('你好', sid=0, speed=1.0)
        self.assertEqual([call.args[0].input for call in synthesize.call_args_list],
                         list(service.FAST_INTRO))

    def test_http_latency_separates_stt_and_tts_without_retaining_content(self):
        engine = Mock()
        engine.generate.return_value = SimpleNamespace(samples=np.zeros(160), sample_rate=16000)
        # No lifespan: do not load models, warm speech, or create an external client.
        client = TestClient(service.app)
        with (
            patch.object(service, 'get_tts', return_value=engine),
            patch.object(service, 'decode_audio', return_value=np.zeros(160, dtype=np.float32)),
            patch.object(service, 'recognize_local', return_value='private-transcript'),
            patch.object(service, 'siliconflow_enabled', return_value=False),
        ):
            self.assertEqual(client.post('/v1/audio/speech?secret=private-query',
                                         json={'input': '請你好'}).status_code, 200)
            self.assertEqual(client.post('/v1/audio/transcriptions',
                                         files={'file': ('private-file.wav', b'private-bytes', 'audio/wav')}
                                         ).status_code, 200)
            metrics = client.get('/health').json()['http_metrics']
        routes = {row['route']: row for row in metrics['routes']}
        for name in ('/v1/audio/speech', '/v1/audio/transcriptions'):
            self.assertGreaterEqual(routes[name]['count'], 1)
            self.assertGreaterEqual(routes[name]['p95_ms'], 0)
        encoded = json.dumps(metrics, ensure_ascii=False)
        for private in ('private-query', 'private-file', 'private-bytes', 'private-transcript', '請你好'):
            self.assertNotIn(private, encoded)

    def test_console_origin_only_allows_speech_not_microphone_upload(self):
        client = TestClient(service.app)
        headers = {'Origin': 'http://127.0.0.1:8000'}
        preflight = client.options('/v1/audio/speech', headers={**headers,
            'Access-Control-Request-Method': 'POST',
            'Access-Control-Request-Headers': 'content-type'})
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers['access-control-allow-origin'], headers['Origin'])
        # Missing input reaches validation only for the allowed console speech route.
        self.assertEqual(client.post('/v1/audio/speech', headers=headers, json={}).status_code, 422)
        self.assertEqual(client.post('/v1/audio/transcriptions', headers=headers).status_code, 403)
        self.assertEqual(client.post('/v1/audio/speech', headers={'Origin': 'https://example.com'},
                                     json={'input': '測試'}).status_code, 403)

    def test_http_latency_counts_failed_tts_not_only_success(self):
        client = TestClient(service.app)
        with patch.object(service, 'ESPEAK', self.root / 'missing.exe'):
            response = client.post('/v1/audio/speech', json={'input': '龘'})
        self.assertEqual(response.status_code, 503)
        metrics = client.get('/health').json()['http_metrics']
        row = next(row for row in metrics['routes'] if row['route'] == '/v1/audio/speech')
        self.assertGreaterEqual(row['statuses']['503'], 1)
        self.assertGreaterEqual(metrics['server_errors'], 1)

    def test_fallback_timeout_returns_bounded_failure_and_cleans_temp(self):
        def timed_out(args, **kwargs):
            self.output = Path(args[args.index('-w') + 1])
            raise subprocess.TimeoutExpired('mock', 30)
        with patch.object(service, 'ESPEAK', self.fallback), \
                patch.object(service.subprocess, 'run', side_effect=timed_out), \
                self.assertRaises(service.HTTPException) as raised:
            service.speech(service.SpeechRequest(input='龘'))
        self.assertEqual(raised.exception.status_code, 504)
        self.assertFalse(self.output.exists())
        self.assertFalse(service._tts_cache)

    def test_fallback_stderr_is_not_returned_as_error_detail(self):
        failed = SimpleNamespace(returncode=1, stderr='private-text-and-path')
        with patch.object(service, 'ESPEAK', self.fallback), \
                patch.object(service.subprocess, 'run', return_value=failed), \
                self.assertRaises(service.HTTPException) as raised:
            service.speech(service.SpeechRequest(input='龘'))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertNotIn('private-text-and-path', raised.exception.detail)

    def test_fallback_rejects_empty_corrupt_and_truncated_wav(self):
        wav = service.wav_bytes(np.zeros(160), 16000)
        for payload in (b'', b'not-wave', wav[:-5]):
            with self.subTest(size=len(payload)):
                def completed(args, payload=payload, **kwargs):
                    self.output = Path(args[args.index('-w') + 1])
                    self.output.write_bytes(payload)
                    return SimpleNamespace(returncode=0)
                with patch.object(service, 'ESPEAK', self.fallback), \
                        patch.object(service.subprocess, 'run', side_effect=completed), \
                        self.assertRaises(service.HTTPException) as raised:
                    service.speech(service.SpeechRequest(input='龘'))
                self.assertEqual(raised.exception.status_code, 503)
                self.assertFalse(self.output.exists())
                self.assertFalse(service._tts_cache)

    def test_valid_fallback_wav_is_cached_and_temp_removed(self):
        wav = service.wav_bytes(np.zeros(160), 16000)
        def completed(args, **kwargs):
            self.output = Path(args[args.index('-w') + 1])
            self.output.write_bytes(wav)
            return SimpleNamespace(returncode=0)
        with patch.object(service, 'ESPEAK', self.fallback), \
                patch.object(service.subprocess, 'run', side_effect=completed) as process:
            first = service.speech(service.SpeechRequest(input='龘'))
            second = service.speech(service.SpeechRequest(input='龘'))
        self.assertEqual(first.body, wav)
        self.assertEqual(second.headers['x-tts-cache'], 'hit')
        process.assert_called_once()
        self.assertFalse(self.output.exists())

    def test_busy_tts_returns_retryable_failure_without_model_or_fallback(self):
        busy = Mock()
        busy.acquire.return_value = False
        with patch.object(service, '_tts_generation_lock', busy), \
                patch.object(service, 'get_tts') as engine, \
                patch.object(service.subprocess, 'run') as process, \
                self.assertRaises(service.HTTPException) as raised:
            service.speech(service.SpeechRequest(input='你好'))
        self.assertEqual(raised.exception.status_code, 503)
        self.assertEqual(raised.exception.headers['Retry-After'], '1')
        busy.acquire.assert_called_once_with(timeout=2.0)
        busy.release.assert_not_called()
        engine.assert_not_called()
        process.assert_not_called()

    def test_busy_local_stt_does_not_enter_recognizer(self):
        busy = Mock()
        busy.acquire.return_value = False
        with patch.object(service, '_stt_inference_lock', busy), \
                patch.object(service, '_recognize_local') as recognize, \
                self.assertRaises(service.HTTPException) as raised:
            service.recognize_local(np.zeros(160, dtype=np.float32))
        self.assertEqual(raised.exception.status_code, 503)
        busy.acquire.assert_called_once_with(timeout=2.0)
        recognize.assert_not_called()

    def test_stt_slot_is_released_after_inference_error(self):
        lock = threading.Lock()
        with patch.object(service, '_stt_inference_lock', lock), \
                patch.object(service, '_recognize_local', side_effect=RuntimeError('mock')), \
                self.assertRaises(RuntimeError):
            service.recognize_local(np.zeros(160, dtype=np.float32))
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()

    def test_finished_fallback_does_not_queue_behind_new_neural_job(self):
        lock = threading.Lock()
        acquired = threading.Event()
        wav = service.wav_bytes(np.zeros(160), 16000)
        def completed(args, **kwargs):
            lock.acquire()
            acquired.set()
            Path(args[args.index('-w') + 1]).write_bytes(wav)
            return SimpleNamespace(returncode=0)
        with patch.object(service, '_tts_generation_lock', lock), \
                patch.object(service, 'ESPEAK', self.fallback), \
                patch.object(service.subprocess, 'run', side_effect=completed), \
                ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(service.speech, service.SpeechRequest(input='龘'))
            try:
                result = future.result(timeout=2)
                self.assertEqual(result.headers['x-tts-engine'], 'espeak-ng-fallback')
            finally:
                if acquired.is_set():
                    lock.release()


if __name__ == '__main__':
    unittest.main()
