"""Staff-only VRoid resource reads with sealed rotation and reviewed choices.

No schema creation, model publication, media upload, billing or startup calls.
The connection is enrolled explicitly after the operator's destination consent.
"""
import asyncio
import hashlib
import json
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from deploy.cloud.avatar_api import ModelBytes
from deploy.cloud.avatar_vrm import validate_vrm
from deploy.cloud.vroid_api import VroidUnavailable, catalogue_models, opaque, shared_candidate
from local_audio_gateway.resident_stream import OwnedStreamResponse

PATH = '/api/v1/service-desk/vroid'
NAMESPACE = 'vroid_library'
OWNER = '5115084'


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, hide_input_in_errors=True)
    application_id: int = Field(repr=False)
    owner_id: str = Field(repr=False, max_length=32)
    client_id: str = Field(repr=False, min_length=8, max_length=256)
    client_secret: str = Field(repr=False, min_length=16, max_length=4096)
    access_token: str = Field(repr=False, min_length=16, max_length=4096)
    refresh_token: str = Field(repr=False, min_length=16, max_length=4096)
    expires_at_ms: int = Field(repr=False, gt=0)


def reviewed_rows(path=None):
    document = json.loads((path or Path(__file__).with_name('vroid_reviewed.json')).read_text(encoding='utf-8'))
    if (document.get('format') != 'neighbour-vroid-reviewed-v1' or not isinstance(document.get('models'), list)
            or len(document['models']) > 400):
        raise ValueError('reviewed_library_not_accepted')
    result = {}
    digests = set()
    for row in document['models']:
        if (not isinstance(row, dict) or not re.fullmatch(r'[0-9]{1,32}', row.get('id', ''))
                or not re.fullmatch(r'[0-9]{1,32}', row.get('version', ''))
                or not re.fullmatch(r'[a-f0-9]{64}', row.get('sha256', ''))
                or row.get('native_render_verified') is not True or row.get('visual_reviewed') is not True or row['id'] in result
                or row['sha256'] in digests or type(row.get('bytes')) is not int
                or not 28 <= row['bytes'] <= 32*1024*1024
                or not all(isinstance(row.get(k), str) and 0 < len(row[k]) <= 500
                           for k in ('name', 'author', 'source', 'terms'))
                or not re.fullmatch(r'https://hub\.vroid\.com/en/characters/[0-9]+/models/' + row['id'], row['source'])):
            raise ValueError('reviewed_library_not_accepted')
        result[row['id']] = row
        digests.add(row['sha256'])
    return result


class Library:
    def __init__(self, operations, client, *, reviewed=None, now=None):
        self.ops, self.client = operations, client
        self.reviewed = reviewed if reviewed is not None else reviewed_rows()
        self.by_digest = {row['sha256']:row for row in self.reviewed.values() if 'sha256' in row}
        self.now = now or (lambda: int(time.time()*1000))
        self.lock = asyncio.Lock()
        self.work = None
        self.pending = set()
        self.closed = False

    async def close(self):
        self.closed = True
        await asyncio.gather(*list(self.pending), return_exceptions=True)

    def start(self, function):
        # One bounded catalogue/download operation at a time. Finish durable
        # token rotation even if the browser disconnects or task is cancelled.
        if self.closed:
            raise VroidUnavailable('library_closing')
        if self.work is not None and not self.work.done():
            raise VroidUnavailable('library_busy')
        task = asyncio.create_task(function())
        self.work = task
        self.pending.add(task)
        def done(value):
            self.pending.discard(value)
            if self.work is value:
                self.work = None
            if not value.cancelled():
                value.exception()
        task.add_done_callback(done)
        return task

    async def owned(self, function):
        return await asyncio.shield(self.start(function))

    def schedule_refresh(self):
        if self.closed or self.work is not None and not self.work.done():
            return False
        self.start(self.refresh_catalog)
        return True

    async def refresh_catalog(self):
        value = await run_in_threadpool(self.connection)
        if not value or value.get('status')!='ready' or value.get('cooldown_until_ms',0)>self.now():
            return
        cached = await run_in_threadpool(self.ops.get,NAMESPACE,'catalogue')
        if cached and 0 <= self.now()-cached['checked_at_ms'] < 60000:
            return
        result = {'checked_at_ms':self.now(),'error':'','new_candidate_ids':[]}
        try:
            token = await self.access()
            document = await self.client().list_models(token,kind='search',keyword='VRoid',count=100,sort='first_published_at')
            candidates = [row for row in catalogue_models(document,kind='search') if shared_candidate(row)]
            result['new_candidate_ids'] = [row['id'] for row in candidates if row['id'] not in self.reviewed]
        except VroidUnavailable as error:
            result['error'] = str(error)
            if str(error)=='rate_limited':
                await self.block_rate_limit()
            # Keep the previous checked candidates, visibly stale, not an empty
            # claim that a failed query proved there are no new models.
            if cached:
                result['new_candidate_ids'] = cached.get('new_candidate_ids',[])
        await run_in_threadpool(self.ops.put,NAMESPACE,'catalogue',result)

    def connection(self):
        row = self.ops.get(NAMESPACE, 'connection')
        return self.ops.open(NAMESPACE, 'connection', row['sealed']) if row else None

    def write_connection(self, value):
        self.ops.put(NAMESPACE, 'connection', {'sealed': self.ops.seal(NAMESPACE, 'connection', value)})

    async def enroll(self, payload):
        async def operation():
            if (payload.application_id != 1745 or payload.owner_id != OWNER
                    or not all(opaque(v, minimum=8 if k=='client_id' else 16, maximum=256 if k=='client_id' else 4096)
                               for k,v in payload.model_dump().items() if k in ('client_id','client_secret','access_token','refresh_token'))
                    or not self.now()+60000 < payload.expires_at_ms <= self.now()+31536000000):
                raise VroidUnavailable('connection_not_accepted')
            if await run_in_threadpool(self.connection) is not None:
                raise VroidUnavailable('connection_already_enrolled')
            account = await self.client().request('GET','/api/account',token=payload.access_token)
            if str(account.get('data',{}).get('user_detail',{}).get('user',{}).get('id')) != OWNER:
                raise VroidUnavailable('connection_account_not_accepted')
            value = {**payload.model_dump(), 'status':'ready', 'revision':1, 'cooldown_until_ms':0}
            await run_in_threadpool(self.write_connection,value)
            actual = await run_in_threadpool(self.connection)
            if actual != value:
                raise VroidUnavailable('connection_save_requires_review')
            return {'connected':True,'program_access':'read_resources_only','credentials_visible':False}
        return await self.owned(operation)

    async def access(self):
        async with self.lock:
            value = await run_in_threadpool(self.connection)
            if not value:
                raise VroidUnavailable('connection_required')
            if value['status'] != 'ready':
                raise VroidUnavailable('refresh_acknowledgement_requires_review')
            if value.get('cooldown_until_ms',0) > self.now():
                raise VroidUnavailable('rate_limited')
            if value['expires_at_ms'] > self.now()+180000:
                return value['access_token']
            value.update(status='refreshing', revision=value['revision']+1)
            # Persist intent before rotation, including across process restarts.
            await run_in_threadpool(self.write_connection,value)
            result = await self.client().refresh(value['client_id'],value['client_secret'],value['refresh_token'])
            value.update(result, status='ready', expires_at_ms=self.now()+result['expires_in']*1000)
            await run_in_threadpool(self.write_connection,value)
            return value['access_token']

    async def block_rate_limit(self):
        value = await run_in_threadpool(self.connection)
        if value:
            value['cooldown_until_ms'] = max(value.get('cooldown_until_ms',0),self.now()+3600000)
            await run_in_threadpool(self.write_connection,value)

    async def catalog(self):
        value = await run_in_threadpool(self.connection)
        discovery = await run_in_threadpool(self.ops.get,NAMESPACE,'catalogue')
        ready = bool(value and value.get('status')=='ready')
        # Loading the picker never downloads hundreds of resources or calls AI.
        return {'connected':ready, 'items':list(self.reviewed.values()) if ready else [],
                'program_access':'read_resources_only','credentials_visible':False,
                'cooldown_until_ms':value.get('cooldown_until_ms',0) if value else 0,
                'validation':'original_file_and_native_AIRI_preview', 'auto_publish':False,
                'discovery':discovery, 'refreshing':bool(self.work and not self.work.done())}

    def credit(self, model_id):
        row = self.by_digest.get(model_id.removeprefix('cloud-vrm-')) if model_id.startswith('cloud-vrm-') else None
        return {key:row[key] for key in ('name','author','source')} if row else None

    async def download(self, identity):
        expected = self.reviewed.get(identity)
        if not expected:
            raise VroidUnavailable('model_not_reviewed')
        async def operation():
            token = await self.access()
            try:
                content, model = await self.client().download_model(token,identity)
            except VroidUnavailable as error:
                if str(error)=='rate_limited':
                    await self.block_rate_limit()
                raise
            version = model['latest_character_model_version']
            if (not shared_candidate(model) or version['id']!=expected['version']
                    or len(content)!=expected['bytes'] or hashlib.sha256(content).hexdigest()!=expected['sha256']):
                raise VroidUnavailable('model_changed_requires_review')
            await run_in_threadpool(validate_vrm,content)
            # Preview bytes only. Existing Save/immutable-CAS route publishes.
            return content, expected
        return await self.owned(operation)


def library_router(authorize, library):
    router = APIRouter()
    preview_slot = threading.BoundedSemaphore(1)

    async def accepted(operation):
        try:
            return await operation
        except VroidUnavailable as error:
            code = str(error)
            messages = {'connection_required':'圖庫連接尚未完成，原有模型仍可使用。',
                'rate_limited':'VRoid 免費服務暫時限流，已停止請求，請稍後再試。',
                'library_busy':'另一個模型正在下載或核對，請等候完成。',
                'model_changed_requires_review':'作者更新了模型，重新核對前先保留原角色。'}
            raise HTTPException(429 if code in ('rate_limited','library_busy') else 503,
                {'message':messages.get(code,'VRoid 圖庫暫時未能使用，原角色保留；沒有自動重試。'),
                 'code':code}) from None
        except ValueError:
            raise HTTPException(422,'模型核對未通過，原角色保留。') from None

    @router.get(PATH + '/models')
    async def catalog():
        authorize()
        result = await accepted(library.catalog())
        library.schedule_refresh()
        return result

    @router.post(PATH + '/connection')
    async def enroll(payload: ConnectionInput):
        authorize()
        return await accepted(library.enroll(payload))

    @router.post(PATH + '/models/{identity}/preview')
    async def preview(identity: str):
        authorize()
        if re.fullmatch(r'[0-9]{1,32}',identity) is None:
            raise HTTPException(404)
        if not preview_slot.acquire(blocking=False):
            raise HTTPException(429,'另一個模型正在下載，請等候完成。')
        try:
            content,row = await accepted(library.download(identity))
        except BaseException:
            preview_slot.release()
            raise
        return OwnedStreamResponse(ModelBytes(content,preview_slot.release),media_type='model/gltf-binary',headers={'Cache-Control':'no-store',
            'X-Content-Type-Options':'nosniff','X-Model-SHA256':row['sha256'],
            'Content-Disposition':'attachment; filename="vroid-model.vrm"'})
    return router
