import json
import time
from typing import Any

class LocalCache:
    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}

    async def get(self, key: str) -> Any | None:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if time.time() > expires_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl_seconds: int = 86400):
        self._store[key] = (value, time.time() + ttl_seconds)

    async def delete(self, key: str):
        self._store.pop(key, None)

    @staticmethod
    def make_key(destination: str, activity: str = None) -> str:
        base = f"seo:{destination.lower().replace(' ', '_')}"
        if activity:
            base += f":{activity.lower().replace(' ', '_')}"
        return base
