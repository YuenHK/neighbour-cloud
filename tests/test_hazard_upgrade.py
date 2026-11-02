import time
from types import SimpleNamespace

import numpy as np
import pytest
from test_ep_patrol import jpeg

from edge_hub.ep_patrol import EpPatrol, PatrolSettings
from edge_hub.events import EventStore
from edge_hub.object_hints import ObjectHints
from edge_hub.observation_cache import ObservationCache


def test_object_hints_are_class_clues_not_hazard_diagnosis():
    raw=np.zeros((1,3549,85),dtype=np.float32)
    raw[0,0,4]=.9;raw[0,0,5+39]=.8
    session=SimpleNamespace(get_inputs=lambda:[SimpleNamespace(name='images')],run=lambda *a:[raw])
    detector=ObjectHints('unused',session)
    assert detector.detect(np.zeros((360,640,3),dtype=np.uint8)) == ['bottle']
    raw[0,0,4]=float('nan')
    with pytest.raises(ValueError):detector.detect(np.zeros((360,640,3),dtype=np.uint8))


def test_exact_cache_never_hides_changed_pixels_or_crosses_restricted_zone():
    clock=[0]
    cache=ObservationCache(lambda:clock[0])
    cache.put(b'image',False,{'litter'})
    assert cache.get(b'image',False)=={'litter'}
    assert cache.get(b'image2',False) is None
    assert cache.get(b'image',True) is None
    clock[0]=31
    assert cache.get(b'image',False) is None
    for i in range(40):cache.put(str(i).encode(),False,set())
    assert len(cache.values)==16


def test_electrical_visual_candidate_has_three_photos_and_never_diagnoses_leakage(tmp_path):
    now=int(time.time()*1000)
    frame={'state':'frame','jpeg':jpeg(),'key':'epoch-1','sn':'SYNTHETIC','captured_at_ms':now}
    store=EventStore(tmp_path/'events.sqlite3')
    manager=EpPatrol(lambda d:dict(frame),store,tmp_path/'data',background=False,
        observe=lambda *a:{'electrical_hazard'},context_source=lambda d,a,c:[
        {'side':side,'jpeg':jpeg(100+i),'frame_key':f'epoch-{i+2}', 'captured_at_ms':now+i+1,'offset':offset}
        for i,(side,offset) in enumerate((('left',30),('right',-30)))])
    try:
        manager.configure('ep-2',PatrolSettings(enabled=True))
        manager.step('ep-2')
        event=store.all()[0]
        assert event.type=='electrical_visual_candidate' and event.severity=='warning'
        assert len(event.details['photos'])==3 and '不能確認漏電' in event.details['caption']
    finally:manager.close();store.close()
