from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from edge_hub.estate_services import EstateStore, ResidentServices
from edge_hub.service_desk import LOCATION_PROMPT, ServiceDeskStore, service_desk_router


@pytest.fixture
def entry(tmp_path):
    cases=ServiceDeskStore(tmp_path/'cases.sqlite3')
    estate=EstateStore(tmp_path/'estate.sqlite3')
    services=ResidentServices(estate,cases)
    queries=[]
    async def search(text):
        queries.append(text)
        return {'context':'虛構來源：紙張與膠樽分開回收。','search_status':'web'}
    services.search=search
    app=FastAPI()
    app.include_router(service_desk_router(cases,lambda _:None,Path('edge_hub/static'),lambda _:pytest.fail('no cloud'),services))
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',123)) as client:
        yield client,cases,queries
    estate.close();cases.close()


@pytest.mark.parametrize('text', ['垃圾應該點分類','垃圾應該點樣分類','垃圾应该怎么分类','我屋企啲垃圾應該點分類','大堂垃圾應該點分類'])
@pytest.mark.parametrize('old_prompt',[False,True])
def test_real_entry_searches_sorting_question_without_case_or_address_prompt(entry,text,old_prompt):
    client,cases,queries=entry
    history=[{'role':'user','content':'今日好攰，只想傾吓'},{'role':'assistant','content':LOCATION_PROMPT if old_prompt else '我喺度，慢慢傾。'}]
    response=client.post('/api/v1/resident/chat',json={'messages':[*history,{'role':'user','content':text}],
        'native_settings':True,'session_id':'1'*32,'submission_id':'2'*32,'stream':True})
    assert response.status_code==200
    result=response.json()
    assert result['object']=='resident.plan'
    assert 'followup' not in result and not cases.list()['items']
    assert queries==[text]
    assert '虛構來源' in result['system_prompt']
    assert '不要延續上一輪的位置追問' in result['system_prompt']


def test_real_litter_report_is_still_delivered_to_staff(entry):
    client,cases,queries=entry
    response=client.post('/api/v1/resident/chat',json={'messages':[{'role':'user','content':'大堂有好多垃圾，垃圾分類桶又滿晒，請幫手清理。'}],
        'native_settings':True,'session_id':'3'*32,'submission_id':'4'*32})
    assert response.status_code==200 and response.json()['followup']['delivered']
    assert cases.list()['items'][0]['kind']=='litter'
    assert not queries
