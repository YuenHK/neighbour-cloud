"""One-time loopback setup. User enters the existing token, never in chat."""
import json
import os
import re
import secrets
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from edge_hub.cloud_credentials import _crypt, settings_root


class Setup(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    token: str = Field(min_length=10, max_length=512, pattern=r'^[A-Za-z0-9_-]+$')
    email: str = Field(min_length=5, max_length=200, pattern=r'^[A-Za-z0-9._+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')
    nonce: str = Field(min_length=32, max_length=100, pattern=r'^[A-Za-z0-9_-]+$')


def create_setup(root=None, *, domain, protect=_crypt):
    if not re.fullmatch(r'[a-z0-9-]+\.ngrok-free\.(?:app|dev)', domain):
        raise ValueError('Use the existing free dev domain only')
    root = Path(root) if root is not None else settings_root()/'remote-access'
    nonce = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware('http')
    async def local_only(request, call_next):
        if (request.client is None or request.client.host != '127.0.0.1'
                or request.headers.get('host') != '127.0.0.1:8002'
                or any(name in request.headers for name in ('x-forwarded-host', 'x-forwarded-for', 'forwarded'))):
            return JSONResponse({'detail': '只限本機設定。'}, status_code=403)
        if request.method == 'POST' and request.headers.get('origin') != 'http://127.0.0.1:8002':
            return JSONResponse({'detail': '來源不正確。'}, status_code=403)
        if request.headers.get('content-length', '').isdecimal() and int(request.headers['content-length']) > 8192:
            return JSONResponse({'detail': '內容太長。'}, status_code=413)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer'})
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(_request, _error):
        return JSONResponse({'detail': '請核對欄位格式，輸入內容不會顯示於錯誤訊息。'}, status_code=422)

    @app.get('/style.css')
    def style():
        return FileResponse(Path(__file__).parent/'static/service-shell.css', media_type='text/css')

    @app.get('/')
    def form():
        if root.exists():
            complete = (root/'READY.json').is_file()
            return HTMLResponse('<meta charset="utf-8"><p>'+('遠端設定已儲存；尚未公開。' if complete else '發現先前未完成的設定，已保留；請先核對，未有覆寫。')+'</p>')
        return HTMLResponse('''<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><link rel="stylesheet" href="/style.css"><title>鄰伴遠端設定</title></head><body class="service-theme"><main><section class="service-card"><h1>鄰伴遠端設定</h1><p>只限本機。使用 ngrok 現成免費 token，唔使另建 API key；不會開啟付費。</p><p>免費網址：'''+domain+'''</p><form id="setup"><label>ngrok 現成 authtoken<input id="token" type="password" autocomplete="off" required maxlength="512"></label><label>只允許這個 Google 帳戶登入<input id="email" type="email" autocomplete="email" required maxlength="200"></label><p>token 只以目前 Windows 帳戶加密存本機；此步不會立即公開平台。</p><button type="submit">加密儲存</button></form><p id="status" role="status"></p></section></main><script>document.querySelector('#setup').addEventListener('submit',async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;const status=document.querySelector('#status');try{const response=await fetch('/save',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:document.querySelector('#token').value,email:document.querySelector('#email').value,nonce:'''+json.dumps(nonce)+'''})});if(!response.ok)throw new Error('save');document.querySelector('#token').value='';document.querySelector('#setup').hidden=true;status.textContent='已加密儲存；互聯網入口仍未公開，下一步會先完成驗證。';}catch{status.textContent='未能完成設定，資料未被覆寫；請核對欄位或回報。';button.disabled=false;}})</script></body></html>''')

    @app.post('/save')
    def save(body: Setup):
        if not secrets.compare_digest(body.nonce, nonce):
            raise HTTPException(403, '請重新開啟本機設定頁。')
        if root.exists():
            raise HTTPException(409, '已有設定，未有覆寫。')
        encrypted = protect(body.token.encode(), decrypt=False)
        root.mkdir(parents=True, exist_ok=False)
        # A failed write leaves an incomplete directory for review, never a
        # successful-looking configuration or a silent overwrite on retry.
        (root/'ngrok-token.dpapi').write_bytes(encrypted)
        profile = {'domain': domain, 'allowed_emails': [body.email.casefold()], 'plan': 'Free',
                   'automatic_paid_upgrade': False, 'published': False}
        (root/'settings.json').write_text(json.dumps(profile), encoding='utf-8')
        (root/'READY.json').write_text('{"version":1}', encoding='utf-8')
        return {'saved': True, 'published': False}
    return app


def from_environment():
    return create_setup(domain=os.environ['NEIGHBOUR_NGROK_DOMAIN'])
