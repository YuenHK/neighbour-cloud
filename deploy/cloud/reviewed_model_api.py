"""Staff-only reviewed application-asset preview; Save remains a separate step."""
import asyncio
import threading

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool

from deploy.cloud.avatar_api import ModelBytes
from deploy.cloud.reviewed_model_imports import ReviewedImportUnavailable
from local_audio_gateway.resident_stream import OwnedStreamResponse

PATH = '/api/v1/service-desk/reviewed-models'


class PreviewAgreement(BaseModel):
    model_config = ConfigDict(extra='forbid')
    accepted_terms: StrictBool
    application_use_only: StrictBool


def reviewed_model_router(authorize, importer, work):
    router = APIRouter(dependencies=[Depends(authorize)])
    preview_slot = threading.BoundedSemaphore(1)

    @router.get(PATH)
    def catalogue():
        return {'items': importer.catalogue(), 'auto_publish': False,
                'purpose': 'neighbour_application_avatar', 'max_model_bytes': 32 * 1024 * 1024}

    @router.post(PATH + '/{identity}/preview')
    async def preview(identity: str, agreement: PreviewAgreement):
        if not agreement.accepted_terms or not agreement.application_use_only:
            raise HTTPException(422, {'code': 'model_terms_not_accepted',
                                     'message': '請先閱讀作者條款，並只在鄰伴作數字人使用。'})
        try:
            row = importer.descriptor(identity)
        except ReviewedImportUnavailable:
            raise HTTPException(404, {'code': 'model_not_reviewed', 'message': '此模型尚未核對。'}) from None
        if not preview_slot.acquire(blocking=False):
            raise HTTPException(429, {'code': 'model_import_busy', 'message': '另一個模型正在準備，請等候完成。'})
        try:
            # AvatarWork keeps the bounded disk/network worker owned until it
            # has actually stopped even when the browser abandons its request.
            async with asyncio.timeout(100):
                content = await work.run(importer.preview, identity)
        except ReviewedImportUnavailable as error:
            preview_slot.release()
            code = str(error)
            status = 429 if code == 'model_import_busy' else 422 if code in (
                'model_changed_requires_review', 'model_archive_invalid', 'model_validation_failed') else 503
            message = '作者檔案已變更或未能核對，原角色保留。' if status == 422 else '模型暫未能下載，原角色保留；沒有自動重試。'
            raise HTTPException(status, {'code': code, 'message': message}) from None
        except TimeoutError:
            preview_slot.release()
            raise HTTPException(504, {'code': 'model_download_timeout', 'message': '準備逾時，沒有發佈或更換角色。'}) from None
        except BaseException:
            preview_slot.release()
            raise
        return OwnedStreamResponse(ModelBytes(content, preview_slot.release), media_type='model/gltf-binary', headers={
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
            'X-Model-SHA256': row.sha256, 'Content-Length': str(len(content)),
            # Necessary for application rendering, not a general asset export.
            'Content-Disposition': 'inline; filename="application-avatar.vrm"',
            'X-Model-Use': 'neighbour-application-only' if row.application_only else 'original-license'})
    return router
