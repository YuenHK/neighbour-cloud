"""Human-run, memory-only transfer into the owned Render service's secret UI.

No .env file, secret stdout, API credential creation, browser automation or
deployment. This transfers only staging DB/ledger credentials and verified
Google metadata; no native model keys, resident data or quota counters.
"""
import argparse
import base64
import ctypes
import json
import os
import struct
from pathlib import Path

from edge_hub.cloud_credentials import _crypt

REMOTE = '/tmp/neighbour-cloud-stage'


def prepare(folder, *, decrypt=None):
    folder = Path(folder).resolve(strict=True)
    decrypt = decrypt or (lambda path: _crypt(path.read_bytes(), decrypt=True))
    resource = json.loads((folder / 'render-service-20261030/RESOURCE.json').read_text(encoding='utf-8'))
    login = json.loads(decrypt(folder / 'render-service-20261030/google-login.dpapi'))
    profile = json.loads((folder / 'turso-provisioning/stage-database-profile.json').read_text(encoding='utf-8'))
    if (resource.get('plan') != 'free' or resource.get('region') != 'singapore'
            or resource.get('workspace') != 'tea-daadio4s728c73836hag'
            or resource.get('service_id') != 'srv-dbi41m2fngtc73c82fq0'
            or resource.get('url') != 'https://neighbour-yuenhk.onrender.com'
            or login.get('format') != 'neighbour-google-login-v1' or login.get('origin') != resource['url']
            or profile.get('format') != 'neighbour-cloud-storage-v2'
            or len(profile.get('databases', {})) != 9
            or any(not entry.get('url', '').startswith('libsql://neighbour-stage-')
                   for entry in profile['databases'].values())):
        raise ValueError('verified_owned_free_staging_resources_required')
    metadata = {'format': 'neighbour-managed-stage-v1', 'service_id': resource['service_id'],
        'origin': resource['url'], 'google_client_id': login['google_client_id'],
        'accounts': login['accounts'], 'database_profile': profile}
    result = {'NEIGHBOUR_CREDENTIAL_BACKEND': 'managed-environment',
        'NEIGHBOUR_SETTINGS_ROOT': REMOTE + '/settings',
        'NEIGHBOUR_CLOUD_CONFIG': REMOTE + '/metadata/host.json',
        'NEIGHBOUR_MANAGED_STAGE': json.dumps(metadata, sort_keys=True, separators=(',', ':')),
        'FORWARDED_ALLOW_IPS': '127.0.0.1'}
    for name, filename in (('NEIGHBOUR_SECRET_TURSO_DATA', 'turso-data-token.dpapi'),
                           ('NEIGHBOUR_SECRET_TURSO_READ', 'turso-read-token.dpapi')):
        token = decrypt(folder / 'turso-provisioning' / filename)
        if (not isinstance(token, bytes) or not 16 <= len(token) <= 4096 or not token.isascii()
                or any(value <= 32 or value == 127 for value in token)):
            raise ValueError('staging_credential_unavailable')
        result[name] = token.decode('ascii')
    key = decrypt(folder / 'turso-provisioning/stage-ledger-key.dpapi')
    if not isinstance(key, bytes) or not 32 <= len(key) <= 128:
        raise ValueError('stage_ledger_key_unavailable')
    result['NEIGHBOUR_SECRET_RETENTION_LEDGER'] = 'base64:' + base64.b64encode(key).decode('ascii')
    return result


def dotenv(values):
    # All generated values are single-line, whitespace-free ASCII. JSON starts
    # with '{', so dotenv preserves its internal quotation marks literally.
    if any(not value or not value.isascii() or any(char.isspace() for char in value)
           or '#' in value or value[0] in ('"', "'") for value in values.values()):
        raise ValueError('single_line_secret_values_required')
    return '\n'.join(f'{name}={value}' for name, value in values.items())


def clipboard_formats(text):
    return [('ExcludeClipboardContentFromMonitorProcessing', b'\x00'),
            ('CanIncludeInClipboardHistory', struct.pack('<I', 0)),
            ('CanUploadToCloudClipboard', struct.pack('<I', 0)),
            (13, (text + '\x00').encode('utf-16-le'))]


class WindowsClipboard:
    def __init__(self):
        if os.name != 'nt':
            raise OSError('Windows clipboard required')
        self.user = ctypes.WinDLL('user32', use_last_error=True)
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        ptr, number = ctypes.c_void_p, ctypes.c_uint
        self.user.CreateWindowExW.argtypes = [ctypes.c_ulong, ctypes.c_wchar_p, ctypes.c_wchar_p,
            ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ptr, ptr, ptr, ptr]
        self.user.CreateWindowExW.restype = ptr
        self.user.OpenClipboard.argtypes = [ptr]
        self.user.OpenClipboard.restype = ctypes.c_int
        self.user.CloseClipboard.restype = ctypes.c_int
        self.user.EmptyClipboard.restype = ctypes.c_int
        self.user.SetClipboardData.argtypes = [number, ptr]
        self.user.SetClipboardData.restype = ptr
        self.user.RegisterClipboardFormatW.argtypes = [ctypes.c_wchar_p]
        self.user.RegisterClipboardFormatW.restype = number
        self.user.GetClipboardSequenceNumber.restype = ctypes.c_ulong
        self.user.DestroyWindow.argtypes = [ptr]
        self.kernel.GlobalAlloc.argtypes = [number, ctypes.c_size_t]
        self.kernel.GlobalAlloc.restype = ptr
        self.kernel.GlobalLock.argtypes = [ptr]
        self.kernel.GlobalLock.restype = ptr
        self.kernel.GlobalUnlock.argtypes = [ptr]
        self.kernel.GlobalFree.argtypes = [ptr]
        self.window = self.user.CreateWindowExW(0, 'STATIC', 'Neighbour local secret transfer',
            0, 0, 0, 0, 0, ptr(-3), None, None, None)
        if not self.window:
            raise OSError('clipboard_owner_unavailable')

    def publish(self, formats):
        if not self.user.OpenClipboard(self.window):
            raise OSError('clipboard_busy')
        try:
            if not self.user.EmptyClipboard():
                raise OSError('clipboard_unavailable')
            for name, data in formats:
                kind = name if type(name) is int else self.user.RegisterClipboardFormatW(name)
                if not kind:
                    raise OSError('clipboard_protection_unavailable')
                handle = self.kernel.GlobalAlloc(2, len(data))
                if not handle:
                    raise OSError('clipboard_memory_unavailable')
                transferred = False
                try:
                    pointer = self.kernel.GlobalLock(handle)
                    if not pointer:
                        raise OSError('clipboard_memory_unavailable')
                    try:
                        ctypes.memmove(pointer, data, len(data))
                    finally:
                        self.kernel.GlobalUnlock(handle)
                    if not self.user.SetClipboardData(kind, handle):
                        raise OSError('clipboard_write_unavailable')
                    transferred = True
                finally:
                    if not transferred:
                        self.kernel.GlobalFree(handle)
            return self.user.GetClipboardSequenceNumber()
        except OSError:
            self.user.EmptyClipboard()  # Only this new item, before publishing success.
            raise
        finally:
            self.user.CloseClipboard()

    def clear_if_current(self, sequence):
        if not self.user.OpenClipboard(self.window):
            return False
        try:
            if self.user.GetClipboardSequenceNumber() != sequence:
                return False
            return bool(self.user.EmptyClipboard())
        finally:
            self.user.CloseClipboard()

    def close(self):
        if self.window:
            self.user.DestroyWindow(self.window)
            self.window = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    args = parser.parse_args()
    try:
        values = dotenv(prepare(args.folder))
        input('Press Enter to copy ONLY staging settings for neighbour-yuenhk. No values will be displayed. ')
        clipboard = WindowsClipboard()
        sequence = None
        try:
            sequence = clipboard.publish(clipboard_formats(values))
            print('Copied. Windows history/cloud-sync exclusion flags set. Paste ONLY into the owned Render Environment page.')
            print('Use Add from .env, paste, then Save only. Do not paste into chat, an editor or another service.')
            input('After saving in Render, press Enter here to clear this clipboard item. ')
        finally:
            if sequence is not None:
                clipboard.clear_if_current(sequence)
            clipboard.close()
        print('Transfer finished. No plaintext file, deployment, model request or robot operation was made.')
    except (OSError, ValueError, KeyError, EOFError, KeyboardInterrupt):
        print('Transfer incomplete or cancelled; no credential values displayed. Please report only this status.')


if __name__ == '__main__':
    main()
