"""Native launch fence used only during/after an explicit cloud cutover.

This marker selects the data authority; it does not erase local data, change
execution policy, clear robot faults or implement an automatic rollback.
"""
import json
import re
from pathlib import Path


def cloud_primary(project_root):
    path = Path(project_root).absolute() / '.runtime/cloud-primary.json'
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if (not path.is_file() or any(item.is_symlink() for item in (path, *path.parents))
                or path.stat().st_size > 16384):
            raise ValueError('invalid')
        info = json.loads(path.read_text(encoding='utf-8'))
        if (not isinstance(info, dict) or info.get('format') != 'neighbour-cloud-primary-v1'
                or info.get('phase') not in ('preparing', 'cloud')
                or not isinstance(info.get('origin'), str)
                or not re.fullmatch(r'https://[a-z0-9-]+\.onrender\.com', info['origin'])
                or not isinstance(info.get('release_id'), str) or not re.fullmatch('[a-f0-9]{32}', info['release_id'])):
            raise ValueError('invalid')
        return info
    except (OSError, ValueError, TypeError, UnicodeError):
        raise RuntimeError('native_writer_fenced_cloud_primary_requires_review') from None


def assert_native_writes_allowed(project_root):
    if cloud_primary(project_root) is not None:
        raise RuntimeError('native_writer_fenced_use_cloud_service')
