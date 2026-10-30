"""Explicit request/startup storage scope. Native mode is the default.

No environment variable activates this scope and no sqlite3 module is replaced.
A future cloud app must bind its core stores explicitly as well as wrap ASGI
requests with this scope; wrapping the current native app alone is insufficient.
"""
from contextlib import contextmanager
from contextvars import ContextVar

_storage = ContextVar('neighbour_storage', default=None)


def current_storage():
    return _storage.get()


@contextmanager
def use_storage(storage):
    if (storage is not None and (not callable(getattr(storage, 'connect', None))
                                or not hasattr(storage, 'settings_root') or not hasattr(storage, 'controls'))):
        raise TypeError('explicit_storage_backend_required')
    token = _storage.set(storage)
    try:
        yield storage
    finally:
        _storage.reset(token)
