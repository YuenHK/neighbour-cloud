"""Read-only automatic routing status; no operator model selector."""
from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse

from edge_hub.resident_models import GEMMA_MODEL


def chat_settings_router(authorize):
    router = APIRouter()

    @router.get('/api/v1/service-desk/chat-settings')
    def get(x_operator_key: str | None = Header(default=None)):
        authorize(x_operator_key)
        return JSONResponse({'model': None, 'label': '以 AIRI 設定為準', 'authority': 'airi', 'default_model': GEMMA_MODEL,
            'automatic': False, 'free_only': None, 'managed_adapter_free_only': True, 'fast_backup': None,
            'local_backup': False, 'primary_deadline_seconds': 12,
            'session_messages': 60, 'session_characters': 16000},
            headers={'Cache-Control': 'no-store'})

    return router
