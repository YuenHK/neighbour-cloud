"""DI container for future cloud startup and ASGI middleware; no auto activation."""
from dataclasses import dataclass

from edge_hub.storage_context import use_storage


@dataclass(frozen=True)
class RuntimeStorage:
    profile: object
    controls: object

    @property
    def settings_root(self):
        return self.profile.settings_root

    def connect(self, *args, **kwargs):
        return self.profile.connect(*args, **kwargs)


class StorageMiddleware:
    def __init__(self, app, storage):
        self.app, self.storage = app, storage

    async def __call__(self, scope, receive, send):
        with use_storage(self.storage):
            await self.app(scope, receive, send)
