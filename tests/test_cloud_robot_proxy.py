import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from deploy.cloud.robot_proxy import robot_router


def test_staff_proxy_is_fixed_origin_bounded_and_never_replays_unknown_commands():
    calls = []
    mode = ['normal']
    staff = [True]
    async def respond(request):
        calls.append(request)
        assert request.url.host == 'synthetic.ngrok-free.app'
        assert request.headers['authorization'] == 'Bearer synthetic-staff-session'
        assert request.headers['origin'] == 'https://cloud.example'
        assert 'x-operator-key' not in request.headers
        if mode[0] == 'network':
            raise httpx.ReadError('synthetic response lost')
        if mode[0] == 'redirect':
            return httpx.Response(307, headers={'Location':'https://evil.invalid/private'})
        if request.url.path.endswith('/frame.jpg'):
            await asyncio.sleep(.03)
            return httpx.Response(200,content=b'synthetic JPEG',headers={'X-Frame-Age-Ms':'1199','X-Frame-State':'frame'})
        return httpx.Response(200,json={'devices':[]})
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            app.state.client = client
            yield
    app = FastAPI(lifespan=lifespan)
    def authorize():
        if not staff[0]:
            raise HTTPException(403)
    profile = {'robot_remote_url':'https://synthetic.ngrok-free.app'}
    app.include_router(robot_router(SimpleNamespace(current=lambda:profile),authorize,lambda:app.state.client))
    with TestClient(app,base_url='https://cloud.example') as client:
        headers = {'Authorization':'Bearer synthetic-staff-session','X-Operator-Key':'must-not-forward'}
        path = '/api/v1/robot/ep/'
        assert client.get(path+'fleet',headers=headers).status_code==200
        count = len(calls)
        staff[0] = False
        assert client.get(path+'fleet',headers=headers).status_code==403 and len(calls)==count
        staff[0] = True
        assert client.get(path+'private-key',headers=headers).status_code==404 and len(calls)==count
        assert client.get(path+'devices/ep-1/frame.jpg?redirect=evil',headers=headers).status_code==422
        assert client.get(path+'devices/ep-1/frame.jpg?after=old',headers=headers).status_code==204
        mode[0] = 'network'
        count = len(calls)
        result = client.post(path+'devices/ep-1/command',headers=headers,json={'direction':'forward'})
        assert result.status_code==503 and result.json()['operation_outcome']=='unknown'
        assert len(calls)==count+1
        mode[0] = 'redirect'
        count = len(calls)
        assert client.get(path+'fleet',headers=headers).status_code==503 and len(calls)==count+1
        profile['robot_remote_url']='http://127.0.0.1:8000'
        assert client.get(path+'fleet',headers=headers).status_code==503 and len(calls)==count+1
