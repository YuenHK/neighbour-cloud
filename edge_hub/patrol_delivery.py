"""Hardware agent's event-only outbox adapter; never opens resident databases.

EpPatrol owns fsync'ed manifests/photos. A manifest is removed only after a
matching cloud receipt. A lost response is retried with the same immutable ID.
"""
import base64
import hashlib
import json
import os
import threading
import time
from pathlib import Path

import httpx

from edge_hub.cloud_credentials import _crypt


class PatrolDelivery:
    def __init__(self, root, origin, credential, *, client=None, clock=time.monotonic):
        from urllib.parse import urlsplit
        if (urlsplit(origin).scheme != 'https' or urlsplit(origin).netloc != 'neighbour-yuenhk-live.onrender.com'
                or urlsplit(origin).path or set(credential) != {'site', 'token'}):
            raise ValueError('pinned_patrol_delivery_required')
        self.root, self.origin, self.credential = Path(root).resolve(), origin, credential
        self.client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=20)
        self.owned = client is None
        self.clock, self.retries, self.lock = clock, {}, threading.Lock()
        self.last = {'state': 'ready', 'pending': 0}
        self.next_cleanup = 0
        self.cleanup_offset = 0

    @classmethod
    def load(cls, root, origin, path, **kwargs):
        credential = json.loads(_crypt(Path(path).read_bytes(), decrypt=True))
        return cls(root, origin, credential, **kwargs)

    def get_event(self, identity):
        return None  # No duplicate local event DB; cloud validates stable identity.

    def capture_allowed(self, size):
        folder = self.root / 'events/ep-patrol'
        # Fleet has at most eight capture workers. Leave >8 complete bundles
        # of headroom so concurrent checks cannot exceed the 512MiB ceiling.
        used = sum(path.stat().st_size for path in folder.glob('*.jpg') if path.is_file())
        if (not 0 < size <= 1_050_000 or used + size > 500 * 1024 * 1024
                or len(list(folder.glob('*.pending.json'))) >= 200):
            raise ValueError('patrol_outbox_full_keep_existing_evidence')

    def add(self, event):
        with self.lock:
            count, next_at = self.retries.get(event.id, (0, 0))
            if self.clock() < next_at:
                raise RuntimeError('delivery_backoff')
            images = {}
            for photo in event.details['photos']:
                target = (self.root / photo['path']).resolve()
                if (not target.is_relative_to(self.root / 'events/ep-patrol') or target.is_symlink()
                        or not target.is_file() or target.stat().st_size > 350000):
                    raise ValueError('invalid_outbox_photo')
                raw = target.read_bytes()
                if hashlib.sha256(raw).hexdigest() != photo['sha256']:
                    raise ValueError('outbox_photo_changed')
                images[photo['side']] = base64.b64encode(raw).decode()
            try:
                response = self.client.post(self.origin + '/api/v1/patrol/delivery',
                    headers={'Authorization': 'Bearer ' + self.credential['token'], 'Origin': self.origin},
                    json={'event': event.model_dump(), 'images': images})
                response.raise_for_status()
                receipt = response.json()
                if (receipt.get('delivered') is not True or receipt.get('event_id') != event.id
                        or receipt.get('digest') != hashlib.sha256(json.dumps(event.model_dump(), sort_keys=True,
                            separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
                        or not isinstance(receipt.get('case_number'), int)):
                    raise ValueError('invalid_delivery_receipt')
                receipt_path = self.root / 'events/ep-patrol' / (event.id + '.receipt.json')
                temporary = receipt_path.with_suffix('.tmp')
                local = {'receipt': receipt, 'photos': event.details['photos']}
                with temporary.open('w', encoding='utf-8') as output:
                    json.dump(local, output)
                    output.flush()
                    os.fsync(output.fileno())
                temporary.replace(receipt_path)
                self.retries.pop(event.id, None)
                self.last = {'state': 'delivered', 'case_number': receipt['case_number']}
                return event
            except (httpx.HTTPError, ValueError, KeyError):
                count += 1
                self.retries[event.id] = count, self.clock() + min(300, 5 * 2**min(count, 6))
                self.last = {'state': 'queued', 'retry_after_seconds': min(300, 5 * 2**min(count, 6))}
                raise RuntimeError('delivery_unconfirmed_retained') from None

    def status(self):
        pending = len(list((self.root / 'events/ep-patrol').glob('*.pending.json')))
        return {**self.last, 'pending': pending, 'paired': True, 'resident_writer': False}

    def close(self):
        if self.owned:
            self.client.close()

    def maintenance(self):
        # Only acknowledged evidence is eligible, using actual cloud completion
        # clock. Unknown/offline receipts retain files. Never touch old EP state.
        if self.clock() < self.next_cleanup:
            return
        self.next_cleanup = self.clock() + 3600
        paths = sorted((self.root / 'events/ep-patrol').glob('*.receipt.json'))
        if not paths:
            return
        offset = self.cleanup_offset % len(paths)
        selected = (paths[offset:] + paths[:offset])[:32]
        self.cleanup_offset += len(selected)
        for path in selected:
            if (self.root / 'events/ep-patrol' / (path.name.replace('.receipt.json', '.pending.json'))).exists():
                continue
            try:
                local = json.loads(path.read_text(encoding='utf-8'))
                if local.get('local_erased'):
                    continue
                event_id = local['receipt']['event_id']
                if path.name != event_id + '.receipt.json':
                    continue
                response = self.client.get(self.origin + '/api/v1/patrol/delivery/' + event_id,
                    headers={'Authorization': 'Bearer ' + self.credential['token'], 'Origin': self.origin})
                response.raise_for_status()
                record = response.json()
                completed = record.get('completed_ms')
                if (record.get('digest') != local['receipt']['digest'] or type(completed) is not int
                        or completed > int(time.time()*1000) - 90 * 86400000):
                    continue
                for photo in local['photos']:
                    target = (self.root / photo['path']).resolve()
                    if (target.is_relative_to(self.root / 'events/ep-patrol') and target.is_file()
                            and not target.is_symlink() and hashlib.sha256(target.read_bytes()).hexdigest() == photo['sha256']):
                        target.unlink()
                path.write_text(json.dumps({'receipt': record, 'photos': [], 'local_erased': True}), encoding='utf-8')
            except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError):
                continue
