from __future__ import annotations

import io
import os
import subprocess
import tempfile
import threading
import time
import wave
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated

import av
import httpx
import numpy as np
import sherpa_onnx
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from opencc import OpenCC
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from edge_hub import azure_voice, gemini_voice, mimo_voice, siliconflow
from edge_hub.cloud_credentials import siliconflow_enabled
from edge_hub.cloud_primary import assert_native_writes_allowed
from edge_hub.observability import HttpMetrics, MetricsMiddleware
from edge_hub.phase_latency import phase_latency
from local_audio_gateway.model_paths import sensevoice_root
from local_audio_gateway.pronunciation import prepare_speech
from local_audio_gateway.resident_stream import stream_router
from local_audio_gateway.singleflight import SynthesisFlights
from local_audio_gateway.stt_availability import SttAvailability
from local_audio_gateway.voice_style import spoken_cantonese, voice_profile

assert_native_writes_allowed(Path(__file__).resolve().parents[1])
_azure_flights = SynthesisFlights(parallel=2)
app = FastAPI(title="智衛尖兵本地廣東話語音服務")


@app.middleware('http')
async def protect_audio_origin(request: Request, call_next):
    origin = request.headers.get('origin')
    if (request.method == 'POST' and origin
            and origin not in {'http://127.0.0.1:4173', 'http://localhost:4173'}
            and not (origin == 'http://127.0.0.1:8000'
                     and request.url.path == '/v1/audio/speech')):
        return JSONResponse({'detail': '來源不允許使用本機語音接口'}, status_code=403)
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:4173", "http://localhost:4173", "http://127.0.0.1:8000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
http_metrics = HttpMetrics(max_routes=16, window=128)
app.add_middleware(MetricsMiddleware, metrics=http_metrics)

MODEL_ROOT = sensevoice_root(Path(__file__).resolve().parents[1])
ESPEAK = Path(
    os.environ.get("ZHIWEI_ESPEAK", r"C:\Program Files\eSpeak NG\espeak-ng.exe")
)
TTS_MODEL_ROOT = Path(
    os.environ.get(
        "ZHIWEI_CANTONESE_TTS_ROOT",
        r"C:\Users\Maker\Models\speech\vits-cantonese-hf-xiaomaiiwn",
    )
)
_recognizer: sherpa_onnx.OfflineRecognizer | None = None
_recognizer_lock = threading.Lock()
_tts: sherpa_onnx.OfflineTts | None = None
_tts_signature = None
_tts_lock = threading.Lock()
_tts_generation_lock = threading.Lock()
_tts_cache_lock = threading.RLock()
_tts_warmed = False
_tts_warm_error = ""
_tts_cache: OrderedDict[tuple[str, float], tuple[bytes, str]] = OrderedDict()
_tts_last: dict[str, object] = {}
_tts_last_resident: dict[str, object] = {}
_gemini_cooldown_until = 0.0
_tts_cloud_last_error: dict[str, object] = {}
_TTS_CACHE_BYTES = 16 * 1024 * 1024
# Match the pinned AIRI chunker's first two punctuation boosts and final hard stop.
FAST_INTRO = ('你好，今日有咩幫到你？', '有咩需要，慢慢同我講就得。', '好，我幫你跟進。')
_stt_last: dict[str, object] = {}
stt_availability = SttAvailability()
_transcript_converter = OpenCC('s2hk')


def cloud_stt_enabled():
    return voice_profile().get('stt_provider') != 'local' and siliconflow_enabled()
# Limit decoded mono 16 kHz audio, not merely compressed upload bytes.
_MAX_STT_SAMPLES = 60 * 16000
# Coroutine admission only; never block the event loop waiting for capacity.
_stt_request_slots = threading.BoundedSemaphore(2)


@app.on_event('startup')
async def open_stt_connection() -> None:
    # One connection pool per service process; never persist the key or audio.
    app.state.stt_client = httpx.AsyncClient(
        timeout=25, follow_redirects=False,
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=2, keepalive_expiry=120),
    )
    app.state.tts_client = httpx.Client(timeout=10, follow_redirects=False,
        limits=httpx.Limits(max_connections=2, max_keepalive_connections=2, keepalive_expiry=120))


@app.on_event('shutdown')
async def close_stt_connection() -> None:
    await app.state.stt_client.aclose()
    app.state.tts_client.close()


class SpeechRequest(BaseModel):
    model: str = "vits-cantonese-yue"
    input: str = Field(min_length=1, max_length=4096)
    voice: str = "yue"
    response_format: str = "wav"
    speed: float = Field(default=1.0, ge=0.5, le=2.0)


@contextmanager
def inference_slot(lock):
    # Bound lock queueing only; this cannot cancel native inference already in progress.
    if not lock.acquire(timeout=2.0):
        raise HTTPException(status_code=503, detail="本地語音引擎忙碌，請稍後重試。",
                            headers={'Retry-After': '1'})
    try:
        yield
    finally:
        lock.release()


def get_recognizer() -> sherpa_onnx.OfflineRecognizer:
    global _recognizer
    if _recognizer is None:
        with _recognizer_lock:
            if _recognizer is None:
                model = MODEL_ROOT / "model.int8.onnx"
                tokens = MODEL_ROOT / "tokens.txt"
                if not model.is_file() or not tokens.is_file():
                    raise RuntimeError(f"找不到 SenseVoice 模型：{MODEL_ROOT}")
                _recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=str(model),
                    tokens=str(tokens),
                    num_threads=min(4, os.cpu_count() or 1),
                    language="yue",
                    use_itn=False,
                    provider="cpu",
                )
    return _recognizer


def get_tts() -> sherpa_onnx.OfflineTts:
    global _tts, _tts_signature
    profile = voice_profile()
    signature = (profile['noise'], profile['duration_noise'])
    if _tts is None or signature != _tts_signature:
        with _tts_lock:
            if _tts is None or signature != _tts_signature:
                model = TTS_MODEL_ROOT / "vits-cantonese-hf-xiaomaiiwn.onnx"
                tokens = TTS_MODEL_ROOT / "tokens.txt"
                lexicon = TTS_MODEL_ROOT / "lexicon.txt"
                rule_fst = TTS_MODEL_ROOT / "rule.fst"
                required = (model, tokens, lexicon, rule_fst)
                if not all(path.is_file() for path in required):
                    raise RuntimeError(f"找不到粵語 VITS 模型：{TTS_MODEL_ROOT}")
                vits = sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=str(model),
                    tokens=str(tokens),
                    lexicon=str(lexicon),
                    length_scale=1.0,
                    noise_scale=profile['noise'],
                    noise_scale_w=profile['duration_noise'],
                )
                model_config = sherpa_onnx.OfflineTtsModelConfig(
                    vits=vits,
                    num_threads=min(4, os.cpu_count() or 1),
                    provider="cpu",
                )
                config = sherpa_onnx.OfflineTtsConfig(
                    model=model_config,
                    rule_fsts=str(rule_fst),
                    max_num_sentences=2,
                )
                _tts = sherpa_onnx.OfflineTts(config)
                _tts_signature = signature
    return _tts


def wav_bytes(samples: np.ndarray, sample_rate: int) -> bytes:
    pcm = np.clip(samples, -1.0, 1.0)
    pcm = (pcm * 32767).astype("<i2", copy=False)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm.tobytes())
    return output.getvalue()


@app.on_event("startup")
def warm_cantonese_tts() -> None:
    global _tts_warmed, _tts_warm_error
    try:
        with _tts_generation_lock:
            get_tts().generate("你好", sid=0, speed=1.0)
        # Only fixed reviewed FAQ text. No microphone audio or arbitrary conversation preloading.
        for text in FAST_INTRO:
            speech(SpeechRequest(input=text, voice='local-yue'))
        profile = voice_profile()
        voice = profile.get('gemini_voice', 'Leda')
        revision = gemini_voice.HK_STYLE_REVISION if voice == 'HKSoft' else 'original'
        suffix = '-'+revision if voice == 'HKSoft' else ''
        intro = Path(__file__).resolve().parents[1]/f'.runtime/voice-samples/gemini-{voice.lower()}{suffix}-intro.wav'
        if profile.get('tts_provider') == 'gemini' and voice in ('Leda', 'HKSoft') and intro.is_file():
            data = intro.read_bytes()
            if data.startswith(b'RIFF') and len(data) < 2_000_000:
                cache_speech((FAST_INTRO[0], 1.0, 'gemini', voice, revision), data, 'gemini-cantonese-'+voice.lower())
        if voice_profile().get('stt_provider') == 'local':
            get_recognizer()
        _tts_warmed = True
        _tts_warm_error = ""
    except (OSError, RuntimeError, ValueError) as exc:
        _tts_warmed = False
        _tts_warm_error = str(exc)


def decode_audio(data: bytes) -> np.ndarray:
    chunks: list[np.ndarray] = []
    sample_count = 0

    def append_converted(converted) -> None:
        nonlocal sample_count
        chunk = converted.to_ndarray().reshape(-1)
        if chunk.size > _MAX_STT_SAMPLES - sample_count:
            raise HTTPException(status_code=413, detail="音訊超過60秒上限，請分段重試。")
        if not np.isfinite(chunk).all():
            raise HTTPException(status_code=400, detail="音訊包含無效取樣。")
        if chunk.size:
            chunks.append(chunk.astype(np.float32, copy=False))
            sample_count += chunk.size

    try:
        with av.open(io.BytesIO(data)) as container:
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=16000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    append_converted(converted)
            for converted in resampler.resample(None):
                append_converted(converted)
    except (av.error.FFmpegError, IndexError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="無法解碼音訊，請使用有效音訊檔。") from exc
    if not chunks:
        raise HTTPException(status_code=400, detail="音訊檔沒有可辨識內容")
    return np.concatenate(chunks).astype(np.float32, copy=False)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "stt": (MODEL_ROOT / "model.int8.onnx").is_file(),
        "tts": (
            TTS_MODEL_ROOT / "vits-cantonese-hf-xiaomaiiwn.onnx"
        ).is_file() or ESPEAK.is_file(),
        "tts_engine": ('azure-hiumaan-f0' if voice_profile().get('tts_provider') == 'azure' else 'mimo-cantonese-bingtang' if voice_profile().get('tts_provider') == 'mimo' else 'gemini-cantonese-'+voice_profile().get('gemini_voice', 'Leda').lower() if voice_profile().get('tts_provider') == 'gemini' else (
            "vits-cantonese"
            if (TTS_MODEL_ROOT / "vits-cantonese-hf-xiaomaiiwn.onnx").is_file()
            else "espeak-ng-fallback"
        )),
        "tts_provider": voice_profile().get('tts_provider', 'local'),
        "tts_scope": 'resident_requests_only',
        "tts_cloud_cooldown": time.monotonic() < _gemini_cooldown_until,
        "tts_cloud_last_error": dict(_tts_cloud_last_error),
        "tts_warmed": _tts_warmed,
        "voice_profile": voice_profile()['name'],
        "tts_warm_error": _tts_warm_error,
        "tts_last": dict(_tts_last),
        "tts_last_resident": dict(_tts_last_resident),
        "tts_cache_entries": len(_tts_cache),
        "stt_last": dict(_stt_last),
        "phase_latency": phase_latency.snapshot(),
        "stt_availability": stt_availability.snapshot(),
        "http_metrics": {
            **http_metrics.snapshot(),
            "scope": "process-local audio HTTP duration; includes upload/decode/queue/response; not microphone-to-playback or conversation acceptance",
        },
        "language": "yue",
        "stt_provider": "siliconflow" if cloud_stt_enabled() else "local-sensevoice",
    }


@app.get("/v1/models")
def models() -> dict[str, object]:
    return {
        "object": "list",
        "data": [
            {"id": azure_voice.MODEL, "object": "model", "owned_by": "azure-f0"},
            {"id": "mimo-v2.5-tts", "object": "model", "owned_by": "xiaomi"},
            {"id": "sensevoice-yue", "object": "model", "owned_by": "local"},
            {"id": "vits-cantonese-yue", "object": "model", "owned_by": "local"},
            {"id": "espeak-ng-yue", "object": "model", "owned_by": "local"},
        ],
    }


@app.post("/v1/audio/transcriptions")
async def transcribe(
    file: Annotated[UploadFile, File()],
    model: Annotated[str, Form()] = "sensevoice-yue",
    response_format: Annotated[str, Form()] = "json",
) -> Response:
    del model
    if not _stt_request_slots.acquire(blocking=False):
        raise HTTPException(status_code=503, detail="語音辨識忙碌，請稍後重試。",
                            headers={'Retry-After': '1'})
    try:
        return await _transcribe_audio(file, response_format)
    finally:
        _stt_request_slots.release()


async def _transcribe_audio(file: UploadFile, response_format: str) -> Response:
    started = time.perf_counter()
    data = await file.read(8 * 1024 * 1024 + 1)
    if len(data) > 8 * 1024 * 1024:
        raise HTTPException(413, '音訊檔過大')
    samples = await run_in_threadpool(decode_audio, data)
    if cloud_stt_enabled():
        text = await stt_availability.run(lambda: siliconflow.transcribe(
            wav_bytes(samples, 16000), len(samples) / 16000,
            client=getattr(app.state, 'stt_client', None),
        ))
    else:
        text = _transcript_converter.convert(await run_in_threadpool(recognize_local, samples))
    _stt_last.update(elapsed_ms=round((time.perf_counter() - started) * 1000),
                     audio_seconds=round(len(samples) / 16000, 2))
    if response_format == "text":
        return Response(text, media_type="text/plain; charset=utf-8")
    return JSONResponse({"text": text})


_stt_inference_lock = threading.Lock()


@phase_latency.measure('local_recognition')
def recognize_local(samples: np.ndarray) -> str:
    with inference_slot(_stt_inference_lock):
        return _recognize_local(samples)


def _recognize_local(samples: np.ndarray) -> str:
    recognizer = get_recognizer()
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, samples)
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


@app.post("/v1/audio/speech")
def speech(request: SpeechRequest) -> Response:
    global _gemini_cooldown_until
    started = time.perf_counter()
    cache_key = (request.input, request.speed)
    profile = voice_profile()
    if request.model == azure_voice.MODEL:
        if request.voice != azure_voice.VOICE:
            raise HTTPException(400, 'Azure 免費語音請選擇曉曼。')
        spoken = spoken_cantonese(request.input)
        key = (spoken, request.speed, 'azure-hiumaan-f0-v2')
        try:
            azure_voice.require_available()

            def generate():
                azure_voice.require_available()
                with _tts_cache_lock:
                    cached = _tts_cache.get(key)
                if cached:
                    return cached[0], True
                data = azure_voice.synthesize(spoken, client=getattr(app.state, 'tts_client', None))
                cache_speech(key, data, 'azure-hiumaan-f0')
                return data, False

            data, cached = _azure_flights.run(key, generate)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, httpx.HTTPError, wave.Error, EOFError):
            raise HTTPException(503, '曉曼語音已暫停、達到可用量或暫時未能合成；文字保留，沒有轉用付費服務。') from None
        return speech_response(data, 'azure-hiumaan-f0', started, cached, request=request)
    if request.model == mimo_voice.MODEL:
        if request.voice != '冰糖':
            raise HTTPException(400, 'MiMo 粵語版請選擇冰糖。')
        key = (request.input, request.speed, 'mimo-bingtang-yue-v1')
        with _tts_generation_lock:
            with _tts_cache_lock:
                cached = _tts_cache.get(key)
            if cached:
                return speech_response(cached[0], cached[1], started, True, request=request)
            try:
                data = mimo_voice.synthesize(spoken_cantonese(request.input), client=getattr(app.state, 'tts_client', None))
            except (OSError, RuntimeError, ValueError, KeyError, TypeError, httpx.HTTPError):
                raise HTTPException(503, 'MiMo 語音暫時未能合成；文字保留，沒有切換其他聲線。') from None
            cache_speech(key, data, 'mimo-cantonese-bingtang')
        return speech_response(data, 'mimo-cantonese-bingtang', started, False, request=request)
    google_model = request.model == 'google-hksoft-tts'
    if google_model and request.voice not in ('resident-yue', 'HKSoft'):
        raise HTTPException(400, 'HKSoft 模型請選擇 HKSoft 或 resident-yue 聲線。')
    if request.voice == 'resident-yue' or google_model:
        if profile.get('tts_provider') != 'gemini':
            raise HTTPException(503, 'Google 語音尚未準備好；可以先閱讀文字。')
        revision = gemini_voice.HK_STYLE_REVISION if profile['gemini_voice'] == 'HKSoft' else 'original'
        cloud_key = (request.input, request.speed, 'gemini', profile['gemini_voice'], revision)
        with _tts_cache_lock:
            cached = _tts_cache.get(cloud_key)
        if cached:
            return speech_response(cached[0], cached[1], started, True, request=request)
        if time.monotonic() >= _gemini_cooldown_until:
            try:
                with inference_slot(_tts_generation_lock):
                    with _tts_cache_lock:
                        cached = _tts_cache.get(cloud_key)
                    if cached:
                        return speech_response(cached[0], cached[1], started, True, request=request)
                    if time.monotonic() < _gemini_cooldown_until:
                        raise ValueError('voice_cooldown')
                    data = gemini_voice.synthesize(spoken_cantonese(request.input), profile['gemini_voice'], request.speed,
                        client=getattr(app.state, 'tts_client', None))
                    _tts_cloud_last_error.clear()
                    cache_speech(cloud_key, data, 'gemini-cantonese-'+profile['gemini_voice'].lower())
                return speech_response(data, 'gemini-cantonese-'+profile['gemini_voice'].lower(), started, False, request=request)
            except (OSError, RuntimeError, ValueError, httpx.HTTPError) as error:
                code = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
                _tts_cloud_last_error.clear()
                _tts_cloud_last_error.update({'http_status': code, 'at_ms': int(time.time()*1000),
                    'reason': 'rate_limited' if code == 429 else 'timeout' if isinstance(error, httpx.TimeoutException)
                    else 'cloud_unavailable'})
                _gemini_cooldown_until = time.monotonic()+60
        raise HTTPException(503, 'Google 語音暫時未能合成；可以先閱讀文字，稍後再試。', headers={'Retry-After': '60'})
    if profile['name'] != 'original':
        cache_key += (profile['name'],)
    # A cached phrase must not wait behind another request's slow inference.
    with _tts_cache_lock:
        cached = _tts_cache.get(cache_key)
        if cached:
            _tts_cache.move_to_end(cache_key)
            return speech_response(cached[0], cached[1], started, True, request=request)
    try:
        with inference_slot(_tts_generation_lock):
            with _tts_cache_lock:
                cached = _tts_cache.get(cache_key)
                if cached:
                    _tts_cache.move_to_end(cache_key)
                    return speech_response(cached[0], cached[1], started, True, request=request)
            spoken, missing = prepare_speech(spoken_cantonese(request.input), TTS_MODEL_ROOT / 'lexicon.txt')
            if missing:
                raise ValueError('unsupported_pronunciation')
            tts = get_tts()
            audio = tts.generate(spoken, sid=0, speed=request.speed*profile['pace'])
            if len(audio.samples) == 0:
                raise ValueError('empty_synthesis')
            data = wav_bytes(np.asarray(audio.samples), audio.sample_rate)
            cache_speech(cache_key, data, 'vits-cantonese')
        return speech_response(data, 'vits-cantonese', started, False, request=request)
    except (OSError, RuntimeError, ValueError):
        pass

    if not ESPEAK.is_file():
        raise HTTPException(
            status_code=503,
            detail="本地語音引擎暫時不可用，請稍後重試。",
        )
    voice = "yue" if request.voice.lower() not in {"yue", "zh-yue"} else request.voice
    words_per_minute = round(175 * request.speed)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as handle:
        output_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                str(ESPEAK),
                "-v",
                voice,
                "-s",
                str(words_per_minute),
                "-w",
                str(output_path),
                "--stdin",
            ],
            input=request.input,
            text=True,
            encoding="utf-8",
            capture_output=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            raise HTTPException(status_code=503, detail="備援語音合成失敗，請稍後重試。")
        if not 0 < output_path.stat().st_size <= _TTS_CACHE_BYTES:
            raise ValueError('invalid fallback audio size')
        data = output_path.read_bytes()
        with wave.open(io.BytesIO(data), 'rb') as generated:
            frames = generated.getnframes()
            if (generated.getnchannels() != 1 or generated.getsampwidth() != 2
                    or generated.getcomptype() != 'NONE' or frames <= 0
                    or not 8000 <= generated.getframerate() <= 96000
                    or frames > _TTS_CACHE_BYTES // 2
                    or len(generated.readframes(frames)) != frames * 2):
                raise ValueError('invalid fallback audio format')
        # cache_speech already owns its independent cache lock, not the model lock.
        cache_speech(cache_key, data, 'espeak-ng-fallback')
        return speech_response(data, 'espeak-ng-fallback', started, False, request=request)
    except subprocess.TimeoutExpired as error:
        raise HTTPException(status_code=504, detail="備援語音合成逾時，請縮短內容後重試。") from error
    except (OSError, ValueError, EOFError, wave.Error) as error:
        raise HTTPException(status_code=503, detail="備援語音輸出無效，請稍後重試。") from error
    finally:
        output_path.unlink(missing_ok=True)


def cache_speech(key: tuple[str, float], data: bytes, engine: str) -> None:
    if len(data) > _TTS_CACHE_BYTES:
        return
    with _tts_cache_lock:
        _tts_cache[key] = (data, engine)
        while len(_tts_cache) > 32 or sum(len(v[0]) for v in _tts_cache.values()) > _TTS_CACHE_BYTES:
            _tts_cache.popitem(last=False)


def speech_response(data: bytes, engine: str, started: float, cached: bool, *, request: SpeechRequest | None = None) -> Response:
    elapsed = round((time.perf_counter() - started) * 1000)
    # Only bounded timing/engine metadata: no spoken text or audio is logged or persisted.
    metadata = {'engine': engine, 'elapsed_ms': elapsed, 'cached': cached, 'at_ms': int(time.time()*1000),
        'requested_voice': request.voice if request and request.voice in ('冰糖', 'resident-yue', 'HKSoft', 'yue', 'local-yue', 'alloy') else 'other'}
    _tts_last.update(metadata)
    if request and (request.voice == 'resident-yue' or request.model in ('google-hksoft-tts', mimo_voice.MODEL, azure_voice.MODEL)):
        _tts_last_resident.update(metadata)
    return Response(data, media_type='audio/wav', headers={
        'X-TTS-Engine': engine,
        'X-TTS-Cache': 'hit' if cached else 'miss',
        'Server-Timing': f'tts;dur={elapsed}',
    })


app.include_router(stream_router(SpeechRequest, voice_profile, spoken_cantonese))
