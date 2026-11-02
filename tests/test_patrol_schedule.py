import threading
import time

from edge_hub.ep_patrol import EpPatrol, PatrolSettings


def wait_for(predicate):
    deadline = time.monotonic()+3
    while not predicate():
        assert time.monotonic() < deadline
        time.sleep(.005)


def test_slow_photo_capture_does_not_hold_other_devices_inference(tmp_path):
    frames = {device:{'state':'frame','jpeg':device.encode(),'sn':device,'key':'epoch-1',
                      'captured_at_ms':int(time.time()*1000)} for device in ('ep-1','ep-2','ep-3')}
    inference_started, release_inference, photo_started, release_photo = [threading.Event() for _ in range(4)]
    seen=[]
    active=[0]
    maximum=[0]
    def observe(jpeg, restricted):
        active[0]+=1
        maximum[0]=max(maximum[0],active[0])
        seen.append(jpeg)
        if jpeg == b'ep-1':
            inference_started.set()
            assert release_inference.wait(3)
        active[0]-=1
        return {'smoke_flame'} if jpeg == b'ep-1' else set()
    def context(device, frame, cancelled):
        photo_started.set()
        assert release_photo.wait(3)
        return []
    manager=EpPatrol(lambda device:dict(frames[device]),None,tmp_path,observe,background=False,context_source=context)
    try:
        manager.configure('ep-1',PatrolSettings(enabled=True))
        manager.dispatch()
        assert inference_started.wait(2)
        for device in ('ep-2','ep-3'):
            manager.configure(device,PatrolSettings(enabled=True))
        manager.dispatch()
        wait_for(lambda:len(manager.turns.snapshot()['waiting'])==2)
        order = manager.turns.snapshot()['waiting']
        # Waiting holds no old pixels. The frame is read at the actual inference turn.
        frames['ep-2']['jpeg']=b'ep-2-latest'
        manager.dispatch()
        assert len(manager.workers)==3  # repeated dispatch cannot queue duplicate pipelines
        release_inference.set()
        assert photo_started.wait(2)
        wait_for(lambda:len(seen)==3)
        assert b'ep-2-latest' in seen and b'ep-2' not in seen
        assert seen[1:]==[b'ep-2-latest' if device=='ep-2' else b'ep-3' for device in order]
        assert maximum[0]==1 and not release_photo.is_set()
        release_photo.set()
        wait_for(lambda:not manager.workers)
    finally:
        release_inference.set();release_photo.set();manager.close()


def test_disabled_waiting_device_does_not_read_frame_or_observe(tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls=[]
    frame={'state':'frame','jpeg':b'one','sn':'synthetic','key':'epoch-1','captured_at_ms':int(time.time()*1000)}
    def source(device):
        calls.append(device)
        return dict(frame)
    def observe(*args):
        entered.set()
        assert release.wait(3)
        return set()
    manager=EpPatrol(source,None,tmp_path,observe,background=False)
    try:
        manager.configure('ep-1',PatrolSettings(enabled=True));manager.dispatch()
        assert entered.wait(2)
        manager.configure('ep-2',PatrolSettings(enabled=True));manager.dispatch()
        wait_for(lambda:manager.turns.snapshot()['waiting']==['ep-2'])
        calls.clear()
        manager.configure('ep-2',PatrolSettings(enabled=False))
        wait_for(lambda:'ep-2' not in manager.workers)
        assert 'ep-2' not in calls
        release.set()
        wait_for(lambda:not manager.workers)
    finally:
        release.set();manager.close()


def test_failed_inference_releases_turn_for_the_next_device(tmp_path):
    seen=[]
    def observe(jpeg, restricted):
        seen.append(jpeg)
        if jpeg == b'ep-1':
            raise ValueError('synthetic inference failure')
        return set()
    manager=EpPatrol(lambda device:{'state':'frame','jpeg':device.encode(),'sn':device,'key':'epoch-1',
                                    'captured_at_ms':int(time.time()*1000)},None,tmp_path,observe,background=False)
    try:
        for device in ('ep-1','ep-2'):
            manager.configure(device,PatrolSettings(enabled=True))
        manager.dispatch()
        wait_for(lambda:not manager.workers)
        assert set(seen)=={b'ep-1',b'ep-2'}
        assert manager.turns.snapshot()['active'] is None
    finally:
        manager.close()


def test_slow_report_delivery_does_not_lock_fleet_status(tmp_path):
    delivery_started,release_delivery,status_read=[threading.Event() for _ in range(3)]
    manager=EpPatrol(lambda device:{'state':'frame','jpeg':b'synthetic','sn':device,'key':'epoch-1',
        'captured_at_ms':int(time.time()*1000)},None,tmp_path,lambda *_:{'smoke_flame'},background=False,context_source=lambda *_:[])
    def report(*args,**kwargs):
        delivery_started.set()
        assert release_delivery.wait(3)
    manager.report=report
    try:
        manager.configure('ep-1',PatrolSettings(enabled=True));manager.dispatch()
        assert delivery_started.wait(2)
        reader=threading.Thread(target=lambda:(manager.status('ep-1'),status_read.set()))
        reader.start()
        assert status_read.wait(.5)
        reader.join(1)
        release_delivery.set()
        wait_for(lambda:not manager.workers)
    finally:
        release_delivery.set();manager.close()
