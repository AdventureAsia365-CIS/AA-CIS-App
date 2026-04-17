import json
import os
from typing import Any

class RedisCache:
    def __init__(self, client=None):
        self._client = client

    async def get(self, key: str) -> Any | None:
        if not self._client:
            return None
        val = await self._client.get(key)
        return json.loads(val) if val else None

    async def set(self, key: str, value: Any, ttl_seconds: int = 86400):
        if not self._client:
            return
        await self._client.set(key, json.dumps(value), ex=ttl_seconds)

    async def delete(self, key: str):
        if not self._client:
            return
        await self._client.delete(key)

    @staticmethod
    def make_key(destination: str, activity: str = None) -> str:
        base = f"seo:{destination.lower().replace(' ', '_')}"
        if activity:
            base += f":{activity.lower().replace(' ', '_')}"
        return base
