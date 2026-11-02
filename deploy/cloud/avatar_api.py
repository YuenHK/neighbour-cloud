"""Staff import and authenticated resident download; no public GitHub upload."""
import asyncio
import re
import sqlite3
import threading

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from deploy.cloud.avatar_assets import MAX_ARCHIVE, MAX_TOTAL, MODEL_ID
from deploy.cloud.avatar_prepare import prepare_archive
from local_audio_gateway.resident_stream import OwnedStreamResponse

STAFF = '/api/v1/service-desk/airi-models'
RESIDENT = '/api/v1/resident/airi-models'
PREPARE = STAFF + '/prepare'
UPLOAD = re.compile(r'^' + STAFF + r'/cloud-live2d-[a-f0-9]{64}$')


class AvatarWork:
    def __init__(self):
        self.pending = set()

    async def save(self, assets, *args):
        return await self.run(assets.put, *args)

    async def run(self, function, *args):
        task = asyncio.create_task(run_in_threadpool(function, *args))
        self.pending.add(task)
        def finished(done):
            self.pending.discard(done)
            if not done.cancelled():
                done.exception()  # Also retrieve failures after client disconnect.
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def close(self):
        await asyncio.gather(*self.pending, return_exceptions=True)


class ModelBytes:
    """Release the slot even if ASGI closes before requesting the first chunk."""
    def __init__(self, content, release):
        self.content, self.release, self.offset, self.closed = content, release, 0, False

    def __iter__(self):
        return self

    def __next__(self):
        if self.closed or self.offset >= len(self.content):
            self.close()
            raise StopIteration
        value = self.content[self.offset:self.offset + 256 * 1024]
        self.offset += len(value)
        return value

    def close(self):
        if not self.closed:
            self.closed = True
            self.content = b''
            self.release()


def avatar_router(assets, presentation, require_staff, principal, work):
    router = APIRouter()
    upload_lock = asyncio.Lock()
    downloads = threading.BoundedSemaphore(2)
    preparation = asyncio.Lock()

    @router.post(PREPARE)
    async def prepare(request: Request, entrypoint: str | None = None):
        require_staff()
        if request.headers.get('content-type') != 'application/zip':
            raise HTTPException(415, '請使用 Live2D ZIP。')
        if preparation.locked() or upload_lock.locked() or work.pending:
            raise HTTPException(429, '另一個模型正在處理；原有角色保留。')
        async with preparation:
            content = bytearray()
            try:
                async with asyncio.timeout(90):
                    async for chunk in request.stream():
                        content.extend(chunk)
                        if len(content) > MAX_ARCHIVE:
                            raise HTTPException(413, '模型 ZIP 不可大於 32 MB。')
                result = await work.run(prepare_archive, bytes(content), entrypoint)
            except TimeoutError:
                raise HTTPException(408, '整理逾時；沒有發佈或更換平台角色。') from None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None
            if 'models' in result:
                return result
            from starlette.responses import Response
            return Response(result['content'], media_type='application/zip', headers={
                'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                'X-Original-Bytes': str(result['original_bytes']),
                'X-Prepared-Bytes': str(result['prepared_bytes'])})

    @router.get(STAFF)
    def models():
        require_staff()
        try:
            items = assets.catalog()
        except sqlite3.Error:
            raise HTTPException(503, '共享模型儲存尚未準備好，原有設定保留。') from None
        return {'items': items, 'max_bytes': MAX_ARCHIVE, 'total_limit': MAX_TOTAL,
                'used_bytes': sum(item['bytes'] for item in items), 'durable': True,
                'active_model': presentation.current()['airi']['stage_model']}

    @router.put(STAFF + '/{identity}')
    async def upload(identity: str, request: Request, name: str):
        require_staff()
        if MODEL_ID.fullmatch(identity) is None or len(name) > 100:
            raise HTTPException(400, '模型名稱或摘要不正確。')
        if request.headers.get('content-type') != 'application/zip':
            raise HTTPException(415, '請使用 Live2D ZIP 模型。')
        if upload_lock.locked() or preparation.locked() or work.pending:
            raise HTTPException(429, '另一個模型正在上載，請等候完成；沒有自動重送。')
        async with upload_lock:
            content = bytearray()
            try:
                async with asyncio.timeout(90):
                    async for chunk in request.stream():
                        content.extend(chunk)
                        if len(content) > MAX_ARCHIVE:
                            raise HTTPException(413, '模型 ZIP 不可大於 32 MB；原有模型保留。')
                # The owned task survives a dropped HTTP response and is tracked
                # by maintenance/shutdown. Unknown acknowledgements are read back.
                return await work.save(assets, identity, name, bytes(content))
            except TimeoutError:
                raise HTTPException(408, '上載逾時；請先重新查閱模型清單核對結果。') from None
            except ValueError as error:
                raise HTTPException(422, str(error)) from None

    @router.get(RESIDENT + '/{identity}')
    def download(identity: str):
        person = principal()
        if person is None:
            raise HTTPException(401, '需要平台登入狀態。')
        if MODEL_ID.fullmatch(identity) is None:
            raise HTTPException(404, '模型不存在。')
        if person.role != 'staff' and identity != presentation.current()['airi']['stage_model']:
            raise HTTPException(403, '居民只可載入目前已發佈的模型。')
        if not downloads.acquire(blocking=False):
            raise HTTPException(429, '模型正在傳送到其他裝置，請稍後再試；原有角色保留。')
        try:
            content = assets.get(identity)
            if content is None:
                raise HTTPException(404, '模型不存在。')
        except ValueError:
            downloads.release()
            raise HTTPException(503, '模型資料未能核對，原有角色保留。') from None
        except BaseException:
            downloads.release()
            raise
        return OwnedStreamResponse(ModelBytes(content, downloads.release), media_type='application/zip', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'Content-Disposition': 'attachment; filename="model.zip"', 'X-Model-SHA256': identity[13:],
            'Content-Length': str(len(content))})
    return router
