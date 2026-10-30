"""Operator-only memory management plus narrowly scoped AIRI pairing."""
from fastapi import APIRouter, Header, HTTPException, Request
from edge_hub.local_operator import operator_page
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field


class MemoryEdit(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    text: str = Field(min_length=1, max_length=1000)
    revision: int = Field(ge=1, le=2147483647)


def memory_router(memory, capabilities, require_operator, static_root):
    router = APIRouter()

    @router.get('/assistant-memory')
    def page(request: Request):
        return HTMLResponse(operator_page((static_root / 'assistant-memory.html').read_text(encoding='utf-8'), request),
            headers={'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
                     'Content-Security-Policy': "default-src 'self'; script-src 'self'; connect-src 'self'; "
                     "media-src 'none'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"})

    @router.get('/assets/assistant-memory.js')
    def script():
        return FileResponse(static_root / 'assistant-memory.js', media_type='text/javascript',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @router.get('/api/v1/assistant/memories')
    def items(x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        return JSONResponse({'items': memory.items(), 'automatic_chat_storage': False,
                             'memory_cloud_upload': False}, headers={'Cache-Control': 'no-store'})

    @router.put('/api/v1/assistant/memories/{identity}')
    def edit(identity: str, change: MemoryEdit, x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        memory.change(identity, change.revision, change.text)
        return {'status': 'updated'}

    @router.delete('/api/v1/assistant/memories/{identity}')
    def delete(identity: str, revision: int, x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        memory.change(identity, revision)
        return {'status': 'deleted'}

    @router.post('/api/v1/assistant/memory-capabilities')
    def pair(x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        return JSONResponse({'token': capabilities.issue(), 'expires_in_seconds': 8*3600,
                             'scope': 'assistant_memory_only'}, headers={'Cache-Control': 'no-store'})

    @router.post('/api/v1/assistant/memory-capabilities/revoke')
    def revoke(x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        capabilities.revoke()
        return {'status': 'revoked'}

    @router.post('/api/v1/assistant/remember')
    def remember(payload: dict, x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        # Same explicit command grammar as AIRI; this is not an arbitrary fact writer.
        from edge_hub.assistant_memory import remember_text
        if set(payload) != {'command'}:
            raise HTTPException(422, 'invalid memory command')
        fact = remember_text({'messages': [{'role': 'user', 'content': payload['command']}]})
        if fact is None:
            raise HTTPException(422, '請以「記住：」開始')
        return {'status': 'remembered', 'id': memory.remember(fact)}

    return router
