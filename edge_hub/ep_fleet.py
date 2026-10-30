"""One SDK process and control store per EP; pairing stays on the primary worker."""
import base64
import ipaddress
import sqlite3
import threading
import time
from pathlib import Path

from edge_hub.ep_console import EpBroker
from edge_hub.ep_discovery import EpDiscovery
from edge_hub.robot_control import ControlError


class EpFleetBroker(EpBroker):
    MAX_DEVICES = 8

    def __init__(self, root, broker_factory=EpBroker, registry_path=None):
        super().__init__(root)
        self.device_lock = threading.RLock()
        self.devices = {}
        self.broker_factory = broker_factory
        self.primary_snapshot = {'connection': 'not_connected', 'control': None}
        self.primary_snapshot_at = None
        self.registry_path = Path(registry_path) if registry_path is not None else root / '.runtime/ep-known.sqlite3'
        self.registry_notice = ''
        self.retired_ips = {}
        self.retired_brokers = []
        self.forgotten = {}
        self.monitor_stop = threading.Event()
        self.monitor_thread = None
        self.monitor_jobs = {}
        self.discovery = EpDiscovery()
        self.load_known()

    def manual_only(self):
        return (self.root / '.runtime/ep-manual-operation.json').exists()

    def auto_active(self):
        return not self.manual_only() and time.monotonic() < self.discovery.until

    def renew_discovery(self):
        if self.manual_only():
            return {'enabled': False, 'mode': 'manual_only', 'error': ''}
        if self.safety_hold():
            raise ControlError('控制故障仍保留，未自動連線。', 423)
        self.discovery.renew()
        self.start_monitor()
        return {'enabled': True, 'mode': 'read_only_connection', 'error': self.discovery.error}

    def start_monitor(self):
        if self.safety_hold():
            self.registry_notice = '機械人控制故障尚未排除，連線及遙控仍受保護。請先完成故障修復。'
            return
        if self.manual_only() and not self.auto_active():
            return
        if self.monitor_thread and self.monitor_thread.is_alive():
            return
        self.monitor_stop.clear()
        def watch():
            while not self.monitor_stop.is_set():
                try:
                    if not self.auto_active() and self.manual_only():
                        self.monitor_stop.wait(.5)
                        continue
                    self.fleet_snapshot()
                    with self.device_lock:
                        entries = list(self.devices.values())
                    for item in entries:
                        if self.monitor_stop.is_set():
                            break
                        old_job = self.monitor_jobs.get(item['id'])
                        if (item.get('monitor_paused') or (old_job and old_job.is_alive())
                                or time.monotonic() < item.get('retry_at', 0)):
                            continue
                        job = threading.Thread(target=self.monitor_device, args=(item,), daemon=True)
                        self.monitor_jobs[item['id']] = job
                        job.start()
                except (ControlError, OSError, RuntimeError):
                    pass  # Next bounded cycle retries; no camera or motion is resumed.
                self.monitor_stop.wait(.5)
        self.monitor_thread = threading.Thread(target=watch, daemon=True)
        self.monitor_thread.start()

    def monitor_device(self, item):
        if item.get('forgotten') or self.safety_hold() or (self.manual_only() and not self.auto_active()):
            return
        try:
            if time.monotonic() - getattr(item['broker'], 'last_view_request', 0) < 4:
                item['broker'].request('video-heartbeat')
            status = item['broker'].request('health')
            item['snapshot'] = status
            item['snapshot_at'] = time.monotonic()
            if item['broker'] is self:
                self.primary_snapshot = status
                self.primary_snapshot_at = item['snapshot_at']
            if status.get('connection') != 'connected' and not item.get('monitor_paused') and not item.get('forgotten') and not self.monitor_stop.is_set():
                self.device_request(item['id'], 'connect')
            item['retry_at'] = time.monotonic() + 2
            item['retry_failures'] = 0
        except ControlError as error:
            if error.status != 409:
                item['snapshot'] = {'connection': 'not_connected', 'control': None}
                if item['broker'] is self:
                    self.primary_snapshot = item['snapshot']
            failures = item.get('retry_failures', 0) + 1
            item['retry_failures'] = failures
            item['retry_at'] = time.monotonic() + (1 if error.status == 409 else min(12, 2 ** min(failures, 4)))

    def load_known(self):
        if not self.registry_path.exists():
            return
        try:
            with sqlite3.connect(self.registry_path.resolve().as_uri() + '?mode=ro', uri=True) as db:
                rows = db.execute('SELECT device_id, name, ip, sn FROM known_ep ORDER BY device_id').fetchall()
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='forgotten_ep'").fetchone():
                    self.forgotten = {sn: {'ip': ip, 'at_ms': stamp} for sn, ip, stamp in
                                      db.execute('SELECT sn,ip,at_ms FROM forgotten_ep')}
            self.retired_ips.update({item['ip']: item['at_ms'] for item in self.forgotten.values()})
            for device_id, name, ip, sn in rows:
                address = ipaddress.IPv4Address(ip)
                if (device_id not in {f'ep-{i}' for i in range(1, 9)} or not address.is_private
                        or address.is_loopback or address.is_unspecified or address.is_multicast or address.is_link_local
                        or not isinstance(sn, str) or not 1 <= len(sn) <= 64):
                    continue
                item = self.register(ip, device_id=device_id)
                item.update(name=str(name)[:40], known_sn=sn, remembered=True)
        except (OSError, ValueError, sqlite3.Error):
            self.registry_notice = '未能讀取已加入的 EP 記錄；原有檔案已保留。'

    def remember(self, item, status):
        sn = status.get('sn')
        if item.get('forgotten') or status.get('connection') != 'connected' or not isinstance(sn, str) or not 1 <= len(sn) <= 64:
            return item
        if item.get('known_sn') == sn and item.get('remembered'):
            return item
        try:
            with self.device_lock:
                if item.get('forgotten'):
                    return item
                canonical = next((other for other in self.devices.values() if other.get('known_sn') == sn), item)
                self.registry_path.parent.mkdir(parents=True, exist_ok=True)
                with sqlite3.connect(self.registry_path) as db:
                    db.execute('CREATE TABLE IF NOT EXISTS known_ep (device_id TEXT PRIMARY KEY, name TEXT NOT NULL, ip TEXT NOT NULL, sn TEXT NOT NULL UNIQUE)')
                    if sn in self.forgotten:
                        db.execute('DELETE FROM forgotten_ep WHERE sn=?', (sn,))
                    db.execute('INSERT INTO known_ep VALUES (?, ?, ?, ?) ON CONFLICT(device_id) DO UPDATE SET name=excluded.name, ip=excluded.ip, sn=excluded.sn',
                               (canonical['id'], canonical['name'], item['ip'], sn))
                if canonical is not item:
                    self.retired_ips[canonical['ip']] = int(time.time() * 1000)
                    if canonical['broker'] is not self:
                        self.retired_brokers.append(canonical['broker'])
                    canonical.update(ip=item['ip'], broker=item['broker'], snapshot=status,
                                     scan_id=item['scan_id'], scan_received_at_ms=item['scan_received_at_ms'])
                    self.devices.pop(item['id'])
                    item = canonical
                self.forgotten.pop(sn, None)
                item.update(known_sn=sn, remembered=True)
        except (OSError, sqlite3.Error):
            self.registry_notice = 'EP 已連線，但未能儲存機體記錄；請保留此頁。'
        return item

    def forget(self, device_id):
        with self.device_lock:
            item = self.devices.get(device_id)
            if not item:
                raise ControlError('記錄已移除。', 404)
            job = self.monitor_jobs.get(device_id)
            if item.get('connecting') or (job and job.is_alive()):
                raise ControlError('正在檢查這台機體，請稍後再刪除。', 409)
            status = item['broker'].request('status')
            if status.get('connection') == 'connected':
                raise ControlError('請先斷開這台機體，再刪除記錄。', 409)
            sn = item.get('known_sn') or status.get('sn') or ''
            stamp = int(time.time()*1000)
            # Archive only registry metadata; never erase control history or service data.
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(self.registry_path) as db:
                db.execute('CREATE TABLE IF NOT EXISTS known_ep (device_id TEXT PRIMARY KEY, name TEXT NOT NULL, ip TEXT NOT NULL, sn TEXT NOT NULL UNIQUE)')
                db.execute('CREATE TABLE IF NOT EXISTS forgotten_ep (sn TEXT PRIMARY KEY, ip TEXT NOT NULL, at_ms INTEGER NOT NULL)')
                db.execute('INSERT OR REPLACE INTO forgotten_ep VALUES (?,?,?)', (sn, item['ip'], stamp))
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='known_ep'").fetchone():
                    db.execute('DELETE FROM known_ep WHERE device_id=?', (device_id,))
            item.update(forgotten=True, monitor_paused=True)
            self.forgotten[sn] = {'ip': item['ip'], 'at_ms': stamp}
            self.retired_ips[item['ip']] = stamp
            if item['broker'] is not self:
                self.retired_brokers.append(item['broker'])
            self.devices.pop(device_id)
            return {'removed': True, 'device_id': device_id}

    def register(self, ip, primary=False, device_id=None):
        with self.device_lock:
            for item in self.devices.values():
                if item['ip'] == ip:
                    return item
            if len(self.devices) >= self.MAX_DEVICES:
                raise ControlError('目前最多同時管理 8 台 EP。', 409)
            device_id = device_id or next(f'ep-{i}' for i in range(1, 9) if f'ep-{i}' not in self.devices)
            index = int(device_id.split('-')[1])
            use_primary = primary or not any(item['broker'] is self for item in self.devices.values())
            broker = self if use_primary else self.broker_factory(self.root, device_id, 12000 + index)
            item = {'id': device_id, 'name': f'EP {index:02}', 'ip': ip, 'broker': broker,
                    'scan_id': 0, 'scan_received_at_ms': 0, 'suppressed_scan': 0}
            self.devices[device_id] = item
            return item

    @staticmethod
    def age_cached_snapshot(status, observed_at, now=None):
        now = time.monotonic() if now is None else now
        elapsed = max(0, int((now-observed_at)*1000)) if observed_at is not None else 5001
        current = {**status, 'status_cached': True, 'status_age_ms': elapsed}
        battery_age = status.get('battery_age_ms')
        if type(battery_age) is int:
            current['battery_age_ms'] = battery_age+elapsed
        if elapsed >= 5000 or (type(battery_age) is int and battery_age+elapsed >= 5000):
            current.update(connection='not_connected', video_enabled=False, control=None, status_stale=True)
        return current

    def fleet_snapshot(self):
        primary_fresh = True
        try:
            primary = self.request('status')
            self.primary_snapshot = primary
            self.primary_snapshot_at = time.monotonic()
        except ControlError as error:
            if error.status != 409:
                raise
            primary_fresh = False
            primary = self.age_cached_snapshot(self.primary_snapshot, self.primary_snapshot_at)
        if primary.get('connection') == 'connected' and primary.get('ip'):
            self.remember(self.register(primary['ip'], primary=True), primary)
        candidates = primary.get('candidates', [])
        if not candidates and primary.get('detected_ip'):
            candidates = [{'ip': primary['detected_ip'], 'scan_id': primary.get('scan_id', 0),
                           'scan_received_at_ms': primary.get('scan_received_at_ms', 0)}]
        candidates = list(candidates)
        if self.auto_active():
            for advertised in self.discovery.snapshot():
                if advertised['sn'] in self.forgotten:
                    continue
                if not any(c.get('ip') == advertised['ip'] for c in candidates):
                    candidates.append({'ip': advertised['ip'], 'advertised_sn': advertised['sn']})
        for candidate in candidates:
            if candidate.get('scan_received_at_ms', 0) <= self.retired_ips.get(candidate['ip'], -1):
                continue
            try:
                item = self.register(candidate['ip'])
            except ControlError:
                continue
            if candidate.get('advertised_sn') and not item.get('known_sn'):
                item['known_sn'] = candidate['advertised_sn']
            item['scan_id'] = candidate.get('scan_id', item['scan_id'])
            item['scan_received_at_ms'] = candidate.get('scan_received_at_ms', 0)
            if item['scan_id'] > item['suppressed_scan']:
                item['monitor_paused'] = False
        with self.device_lock:
            entries = list(self.devices.values())
        result = []
        for item in entries:
            try:
                status = primary if item['broker'] is self else item['broker'].request('status')
                # A primary worker is never allowed to masquerade as two EPs.
                if status.get('ip') and status['ip'] != item['ip']:
                    status = {'connection': 'not_connected', 'control': None}
                if (status.get('connection') == 'connected' and type(status.get('battery_age_ms')) is int
                        and status['battery_age_ms'] >= 5000):
                    status = {**status, 'connection': 'not_connected', 'video_enabled': False,
                              'control': None, 'status_stale': True}
                item['snapshot'] = status
                if item['broker'] is not self or primary_fresh:
                    item['snapshot_at'] = time.monotonic()
                item = self.remember(item, status)
            except ControlError as error:
                status = (self.age_cached_snapshot(item.get('snapshot', {'connection': 'not_connected', 'control': None}), item.get('snapshot_at'))
                          if error.status == 409 else
                          {'connection': 'not_connected', 'control': None, 'error': '連線中斷，請重試。'})
            patrol = getattr(self, 'patrol', None)
            result.append({**status, 'patrol': patrol.status(item['id']) if patrol else {}, 'id': item['id'], 'name': item['name'], 'ip': item['ip'],
                           'sn': status.get('sn') or item.get('known_sn') or '',
                           'scan_id': item['scan_id'], 'scan_received_at_ms': item['scan_received_at_ms'],
                           'remembered': item.get('remembered', False),
                           'auto_reconnect': not self.safety_hold() and (not self.manual_only() or self.auto_active()) and not item.get('monitor_paused', False),
                           'auto_connect_suppressed_scan': item['suppressed_scan']})
        return {'devices': sorted(result, key=lambda item: (item['connection'] != 'connected', item.get('sn', ''), item['id'])), 'max_devices': self.MAX_DEVICES, 'server_time_ms': int(time.time() * 1000),
                'notice': self.registry_notice, 'safety_hold': self.safety_hold(),
                'manual_only': self.manual_only() and not self.auto_active(),
                'discovery_active': self.auto_active(), 'discovery_error': self.discovery.error,
                'qr_revision': primary.get('qr_revision', ''),
                'auto_monitoring': bool(self.monitor_thread and self.monitor_thread.is_alive()),
                'pairing_diagnostics': primary.get('pairing_diagnostics', {})}

    def device_request(self, device_id, operation, payload=None):
        if self.safety_hold():
            return EpBroker.request(self, operation, payload)
        with self.device_lock:
            item = self.devices.get(device_id)
            if item is not None and operation == 'connect':
                if item.get('forgotten') or item.get('connecting'):
                    raise ControlError('機體記錄正在更新，請稍候。', 409)
                item['connecting'] = True
        if item is None:
            raise ControlError('找不到這台 EP；請重新掃碼。', 404)
        if operation == 'connect':
            # The route selects the target; caller data cannot redirect another EP.
            payload = {'ip': item['ip'], 'confirmed': True}
            if item.get('known_sn'):
                payload['expected_sn'] = item['known_sn']
        if operation == 'disconnect':
            item['suppressed_scan'] = item['scan_id']
            item['monitor_paused'] = True
        try:
            result = item['broker'].request(operation, payload)
            if operation == 'connect':
                canonical = self.remember(item, result)
                result = {**result, 'canonical_device_id': canonical['id']}
            return result
        finally:
            if operation == 'connect':
                with self.device_lock:
                    item['connecting'] = False

    def device_frame(self, device_id, after=''):
        with self.device_lock:
            item = self.devices.get(device_id)
        if item is None:
            raise ControlError('找不到這台 EP。', 404)
        return item['broker'].frame_snapshot(after)

    def patrol_frame(self, device_id):
        """Passively consume existing video; never start a worker or keep the camera alive."""
        with self.device_lock:
            item = self.devices.get(device_id)
        if item is None:
            raise ControlError('找不到這台 EP。', 404)
        result = item['broker'].frame_snapshot(touch=False)
        return {**result, 'sn': item.get('known_sn') or item.get('snapshot', {}).get('sn', ''), 'device_id': device_id}

    def arm_patrol_context(self, device_id):
        frame = self.patrol_frame(device_id)
        if frame.get('state') != 'frame':
            raise ControlError('請先開啟鏡頭。', 409)
        return self.device_request(device_id, 'context-arm', {})

    def patrol_context(self, device_id, frame, cancelled=lambda: False):
        result = self.device_request(device_id, 'context-start', {'frame_key': frame['key'],
            'captured_at_ms': frame['captured_at_ms'], 'camera_pose': frame.get('camera_pose')})
        deadline = time.monotonic()+22
        try:
            while time.monotonic() < deadline and not cancelled():
                result = self.device_request(device_id, 'context-status', {'job_id': result.get('job_id') or result.get('id')})
                if result.get('state') == 'completed' and result.get('restored') is True:
                    photos = result.get('photos', [])
                    if len(photos) != 2 or {photo.get('side') for photo in photos} != {'left', 'right'}:
                        raise ControlError('左右相片未拍齊。', 503)
                    for photo in photos:
                        photo['jpeg'] = base64.b64decode(photo.pop('jpeg_base64'), validate=True)
                        if len(photo['jpeg']) > 350000 or not photo['jpeg'].startswith(b'\xff\xd8'):
                            raise ControlError('環境相片格式不符。', 503)
                    return photos
                if result.get('state') != 'capturing':
                    raise ControlError(result.get('error') or '相片或雲台恢復未確認，未建立完整回報。', 409)
                time.sleep(.2)
            raise ControlError('左右環境攝影已取消或逾時。', 409)
        finally:
            if result.get('state') != 'completed':
                try:
                    self.device_request(device_id, 'context-cancel', {})
                except ControlError:
                    pass  # Disconnected worker cannot retain an active software context job.

    def close(self):
        self.discovery.close()
        self.monitor_stop.set()
        if self.monitor_thread:
            self.monitor_thread.join(timeout=3)
        for job in list(self.monitor_jobs.values()):
            job.join(timeout=1)
        with self.device_lock:
            peers = [item['broker'] for item in self.devices.values() if item['broker'] is not self]
        for peer in peers:
            peer.close()
        for peer in self.retired_brokers:
            peer.close()
        super().close()
