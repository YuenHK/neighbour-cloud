"""Explicit host-managed credential references for a future cloud host.

Windows DPAPI blobs are never decoded or converted by this module. A cloud
settings file contains only an allowlisted reference, not the actual secret.
The host supplies secrets through systemd or its runtime environment. This
does not encrypt environment variables itself or change their host protection.
"""
import os
import stat
from pathlib import Path

PREFIX = b'NEIGHBOUR-SYSTEMD-CREDENTIAL-v1:'
ENV_PREFIX = b'NEIGHBOUR-HOST-SECRET-v1:'
VARIABLES = {'cloudflare-gemma-key': 'NEIGHBOUR_SECRET_CLOUDFLARE_GEMMA',
             'azure-speech-f0-key': 'NEIGHBOUR_SECRET_AZURE_SPEECH_F0',
             'tavily-key': 'NEIGHBOUR_SECRET_TAVILY',
             'turso-data-token': 'NEIGHBOUR_SECRET_TURSO_DATA',
             'retention-ledger-key': 'NEIGHBOUR_SECRET_RETENTION_LEDGER'}
NAMES = frozenset(VARIABLES)


def backend():
    value = os.environ.get('NEIGHBOUR_CREDENTIAL_BACKEND', '')
    if value not in ('', 'systemd', 'managed-environment'):
        raise RuntimeError('Unsupported credential backend')
    return value


def enabled():
    return bool(backend())


def settings_directory():
    value = os.environ.get('NEIGHBOUR_SETTINGS_ROOT', '')
    path = Path(value)
    if not value or not path.is_absolute() or path == path.parent:
        raise RuntimeError('An explicit persistent cloud settings directory is required')
    if not path.is_dir() or path.is_symlink():
        raise RuntimeError('The cloud settings directory must be provisioned first')
    return path


def reference(name, *, mode='systemd'):
    if name not in NAMES:
        raise ValueError('Unsupported cloud credential')
    if mode not in ('systemd', 'managed-environment'):
        raise ValueError('Unsupported credential reference backend')
    return (PREFIX if mode == 'systemd' else ENV_PREFIX) + name.encode('ascii')


def decrypt_reference(data):
    mode = backend()
    prefix = PREFIX if mode == 'systemd' else ENV_PREFIX
    if not mode or not isinstance(data, bytes) or not data.startswith(prefix):
        raise RuntimeError('A cloud credential reference is required')
    try:
        name = data[len(prefix):].decode('ascii')
    except UnicodeError:
        raise RuntimeError('Invalid cloud credential reference') from None
    if name not in NAMES:
        raise RuntimeError('Unsupported cloud credential reference')
    if mode == 'managed-environment':
        try:
            secret = os.environ[VARIABLES[name]].encode('ascii')
            if (not 1 <= len(secret) <= 4096 or any(byte <= 32 or byte == 127 for byte in secret)):
                raise ValueError('invalid secret')
        except (KeyError, UnicodeError, ValueError):
            raise RuntimeError('Private service credential cannot be read') from None
        return secret
    directory = os.environ.get('CREDENTIALS_DIRECTORY', '')
    root = Path(directory)
    if not directory or not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise RuntimeError('Private service credentials are unavailable')
    target = root / name
    # Do not follow a credential symlink or read devices/FIFOs. Open the exact
    # path once with O_NOFOLLOW on Linux, then inspect the descriptor itself.
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    descriptor = None
    try:
        if target.is_symlink():
            raise OSError('symlink')
        descriptor = os.open(target, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 4096:
            raise OSError('invalid credential file')
        secret = os.read(descriptor, 4097).strip()
        if not 1 <= len(secret) <= 4096 or not secret.isascii() or any(byte <= 32 or byte == 127 for byte in secret):
            raise OSError('invalid credential bytes')
        return secret
    except OSError:
        # Filenames, key values and low-level provider errors never enter logs.
        raise RuntimeError('Private service credential cannot be read') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)
