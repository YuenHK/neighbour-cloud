"""Known operational JSON controls; cloud scope never falls back to local files."""
import json
import os
from uuid import uuid4

from edge_hub.storage_context import current_storage

NAMES = {'azure-voice-control.json', 'cloudflare-gemma-quota-stop.json',
         'cloudflare-gemma-cooldown.json'}


def read_control(root, name):
    if name not in NAMES:
        raise ValueError('unsupported_control_state')
    storage = current_storage()
    if storage is not None:
        return storage.controls.read(name)
    path = root / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def write_control(root, name, value):
    if name not in NAMES:
        raise ValueError('unsupported_control_state')
    storage = current_storage()
    if storage is not None:
        storage.controls.write(name, value)
        return
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
