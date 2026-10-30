"""Final closed-file check for an offline backup; never a live writer fence."""
import hashlib
import re
from pathlib import Path

SUFFIXES = ('-wal', '-shm', '-journal')


def unchanged_closed_backup(path, expected_sha256):
    try:
        path = Path(path).absolute()
        if (not isinstance(expected_sha256, str) or not re.fullmatch('[a-f0-9]{64}', expected_sha256)
                or not path.is_file() or any(item.is_symlink() for item in (path, *path.parents))
                or path.stat().st_size > 128 * 1024 * 1024):
            return False

        def no_sidecars():
            return not any(Path(str(path) + suffix).exists() for suffix in SUFFIXES)

        if not no_sidecars():
            return False
        before = path.stat()
        with path.open('rb') as stream:
            current = hashlib.file_digest(stream, 'sha256').hexdigest()
        after = path.stat()
        return (current == expected_sha256 and no_sidecars()
                and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
                and not any(item.is_symlink() for item in (path, *path.parents)))
    except (OSError, ValueError, TypeError):
        return False
