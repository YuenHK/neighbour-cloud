"""Windows current-user DPAPI storage. Credentials never enter source or browser profiles."""
from __future__ import annotations

import ctypes
import os
from functools import lru_cache
from pathlib import Path


def settings_root() -> Path:
    from edge_hub.storage_context import current_storage
    storage = current_storage()
    if storage is not None:
        return storage.settings_root
    from edge_hub import cloud_host_credentials
    if cloud_host_credentials.enabled():
        return cloud_host_credentials.settings_directory()
    root = os.environ.get('LOCALAPPDATA')
    if not root:
        raise RuntimeError('Windows LOCALAPPDATA is required')
    return Path(root) / 'ZhiweiJianbing'


def credential_path() -> Path:
    return settings_root() / 'siliconflow-key.dpapi'


def _crypt(data: bytes, *, decrypt: bool) -> bytes:
    from edge_hub import cloud_host_credentials
    if cloud_host_credentials.enabled():
        if not decrypt:
            raise RuntimeError('Cloud secrets must be provisioned outside the application')
        return cloud_host_credentials.decrypt_reference(data)
    if os.name != 'nt':
        raise RuntimeError('Windows DPAPI is required')

    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_uint32), ('data', ctypes.c_void_p)]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    target = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(Blob)]
    fn.restype = ctypes.c_int
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise RuntimeError('Windows credential encryption/decryption failed')
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def save_siliconflow_key(key: str) -> None:
    if not key.startswith('sk-') or not 16 <= len(key) <= 256 or not key.isascii():
        raise ValueError('Invalid API key format')
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # Refuse to overwrite a pre-existing user credential silently.
    encrypted = _crypt(key.encode(), decrypt=False)
    with path.open('xb') as output:
        output.write(encrypted)
    siliconflow_key.cache_clear()


@lru_cache(maxsize=1)
def siliconflow_key() -> str:
    return _crypt(credential_path().read_bytes(), decrypt=True).decode()


def siliconflow_enabled() -> bool:
    return (
        os.environ.get('ZHIWEI_SILICONFLOW_DISABLED', '0') != '1'
        and os.environ.get('ZHIWEI_LLM_PROVIDER', 'auto') != 'local'
        and credential_path().is_file()
    )
