import time
import importlib
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from test_ep_patrol import jpeg

from edge_hub.ep_patrol import EpPatrol, PatrolSettings, patrol_router
from edge_hub.events import EventStore
from edge_hub.patrol_followup import PatrolFollowup, followup_router
from edge_hub.resident_cases import progress_query
from edge_hub.service_desk import ReviewCase, ServiceDeskStore, service_desk_router


@pytest.fixture
def flow(tmp_path, monkeypatch):
    events=EventStore(tmp_path/'events.sqlite3')
    cases=ServiceDeskStore(tmp_path/'cases.sqlite3')
    followup=PatrolFollowup(events,cases,tmp_path/'data')
    frame={'state':'frame','jpeg':jpeg(),'key':'epoch-1','sn':'SYNTHETIC', 'captured_at_ms':int(time.time()*1000)}
    manager=EpPatrol(lambda _:dict(frame),events,tmp_path/'data',lambda *_:{'smoke_flame'},background=False,followup=followup,
        context_source=lambda _,anchor,cancelled:[{'side':side,'jpeg':jpeg(100+i),'frame_key':'epoch-'+side,
            'captured_at_ms':anchor['captured_at_ms']+i+1} for i,side in enumerate(('left','right'))])
    def auth(key):
        if key!='synthetic':raise HTTPException(403)
    app=FastAPI()
    deployed_app=importlib.import_module('edge_hub.app')
    monkeypatch.setattr(deployed_app,'store',events)
    monkeypatch.setattr(deployed_app,'patrol_followup',followup)
    monkeypatch.setattr(deployed_app,'require_operator',auth)
    app.add_api_route('/api/v1/events/{event_id}',deployed_app.update_event_status,methods=['PATCH'])
    app.include_router(patrol_router(manager,auth))
    app.include_router(followup_router(followup,auth))
    app.include_router(service_desk_router(cases,auth,Path('edge_hub/static'),lambda _:pytest.fail('no cloud')))
    manager.configure('ep-1',PatrolSettings(enabled=True,zone='合成大堂'))
    manager.step('ep-1')
    with TestClient(app,base_url='http://127.0.0.1:8000',client=('127.0.0.1',123)) as client:
        yield manager,events,cases,followup,client
    manager.close();cases.close();events.close()


AUTH={'X-Operator-Key':'synthetic'}


def test_photo_report_staff_progress_and_resident_query_are_one_numbered_flow(flow):
    manager,events,cases,followup,client=flow
    event=events.all()[0]
    rows=client.get('/api/v1/service-desk/requests',headers=AUTH).json()['items']
    assert len(rows)==1
    case=rows[0]
    assert case['source_event_id']==event.id and case['status']=='new'
    for side in ('event','left','right'):
        assert client.get(f'/api/v1/patrol/events/{event.id}/photo?side={side}',headers=AUTH).status_code==200
    followup.ensure(event);manager.deliver_pending()
    assert len(cases.list()['items'])==1
    updated=client.patch('/api/v1/service-desk/requests/'+case['id'],headers=AUTH,
        json={'expected_revision':1,'status':'acknowledged','note':'已查看相片，職員前往核實。'}).json()
    assert updated['revision']==2 and events.get_event(event.id).status=='confirmed'
    query=progress_query(f'查個案{case["case_number"]}進度',[],cases)
    assert '職員前往核實' in query and '正在跟進' in query
    done=client.patch('/api/v1/service-desk/requests/'+case['id'],headers=AUTH,
        json={'expected_revision':2,'status':'resolved','note':'已到場處理完成。'})
    assert done.status_code==200 and events.get_event(event.id).status=='resolved'
    assert '已到場處理完成' in cases.progress(str(case['case_number']))
    assert client.patch('/api/v1/service-desk/requests/'+case['id'],headers=AUTH,
        json={'expected_revision':1,'status':'resolved'}).status_code==409


def test_event_review_uses_revision_and_false_positive_does_not_erase_staff_note(flow):
    _,events,cases,followup,_=flow
    event=events.all()[0];case=cases.list()['items'][0]
    with pytest.raises(HTTPException) as error:
        followup.review_event(event,'confirmed',None)
    assert error.value.status_code==409
    cases.review(case['id'],ReviewCase(expected_revision=1,status='acknowledged',note='原職員核對紀錄'))
    with pytest.raises(HTTPException):followup.review_event(event,'false_positive',1)
    result=followup.review_event(event,'false_positive',2)
    assert result.status=='false_positive'
    row=cases.list()['items'][0]
    assert row['status']=='resolved' and row['note']=='原職員核對紀錄'
    assert row['patrol_status']=='false_positive'


def test_mirror_failure_is_durable_and_retry_does_not_duplicate_case_or_activity(flow,monkeypatch):
    _,events,cases,followup,_=flow
    event=events.all()[0];case=cases.list()['items'][0]
    original=events.update_status
    monkeypatch.setattr(events,'update_status',lambda *_:(_ for _ in ()).throw(OSError('synthetic db failure')))
    updated=cases.review(case['id'],ReviewCase(expected_revision=1,status='acknowledged',note='已接手'))
    assert updated['patrol_sync_pending'] and events.get_event(event.id).status=='pending'
    restarted=PatrolFollowup(events,cases,flow[0].data_root)
    monkeypatch.setattr(events,'update_status',original)
    restarted.flush_pending();restarted.flush_pending()
    assert events.get_event(event.id).status=='confirmed'
    assert not cases.list()['items'][0]['patrol_sync_pending']
    assert len(cases.list()['items'])==1
    assert cases.db.execute('SELECT COUNT(*) FROM service_case_activity').fetchone()[0]==2


def test_new_case_delivery_failure_retains_photo_manifest_and_replays_once(flow,monkeypatch):
    manager,events,cases,followup,_=flow
    original=followup.ensure
    monkeypatch.setattr(followup,'ensure',lambda *_:(_ for _ in ()).throw(OSError('synthetic case db failure')))
    frame={'state':'frame','jpeg':jpeg(150),'key':'epoch-2','sn':'SYNTHETIC', 'captured_at_ms':int(time.time()*1000)}
    sides=[{'side':side,'jpeg':jpeg(100+i),'frame_key':'epoch-'+side,
            'captured_at_ms':frame['captured_at_ms']+i+1} for i,side in enumerate(('left','right'))]
    manager.report('ep-1',{'zone':'合成第二位置'},frame,'litter',sides)
    assert len(events.all())==2 and len(cases.list()['items'])==1
    assert len(list((manager.data_root/'events/ep-patrol').glob('*.pending.json')))==1
    monkeypatch.setattr(followup,'ensure',original)
    manager.deliver_pending();manager.deliver_pending()
    assert len(cases.list()['items'])==2
    assert not list((manager.data_root/'events/ep-patrol').glob('*.pending.json'))
    assert len(list((manager.data_root/'events/ep-patrol').glob('*.jpg')))==6


def test_followup_metadata_and_creation_are_local_staff_only(flow):
    _,events,_,_,client=flow
    event=events.all()[0]
    assert client.get('/api/v1/patrol/followups').status_code==403
    assert client.get('/api/v1/patrol/followups',headers=AUTH).status_code==200
    assert client.post(f'/api/v1/patrol/events/{event.id}/followup',headers={**AUTH,'Origin':'https://outside.invalid'}).status_code==403


def test_deployed_event_patch_updates_case_and_rejects_stale_or_boolean_revision(flow):
    _,events,cases,_,client=flow
    event=events.all()[0]
    url='/api/v1/events/'+event.id
    assert client.patch(url,json={'status':'confirmed','expected_revision':1}).status_code==403
    assert client.patch(url,headers=AUTH,json={'status':'confirmed','expected_revision':True}).status_code==422
    assert client.patch(url,headers=AUTH,json={'status':'confirmed'}).status_code==409
    response=client.patch(url,headers=AUTH,json={'status':'confirmed','expected_revision':1})
    assert response.status_code==200 and response.json()['status']=='confirmed'
    assert cases.list()['items'][0]['status']=='acknowledged'
    assert client.patch(url,headers=AUTH,json={'status':'resolved','expected_revision':1}).status_code==409
    assert client.patch(url,headers=AUTH,json={'status':'false_positive','expected_revision':2}).status_code==200
    assert cases.list()['items'][0]['patrol_status']=='false_positive'


def test_recovery_after_case_commit_without_link_keeps_completed_case_closed(flow):
    _,events,cases,followup,_=flow
    event=events.all()[0];case=cases.list()['items'][0]
    cases.review(case['id'],ReviewCase(expected_revision=1,status='resolved',note='原職員完成紀錄'))
    with cases.db:
        cases.db.execute('DELETE FROM patrol_case_links WHERE case_id=?',(case['id'],))
    events.update_status(event.id,'pending')  # isolated simulation of the interrupted cross-DB delivery
    followup.ensure(events.get_event(event.id))
    rows=cases.list()['items']
    assert len(rows)==1 and rows[0]['status']=='resolved' and rows[0]['note']=='原職員完成紀錄'
    assert events.get_event(event.id).status=='resolved'
