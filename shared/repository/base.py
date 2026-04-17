from abc import ABC, abstractmethod
from typing import Any

class BaseRepository(ABC):
    def __init__(self, conn):
        self.conn = conn

    @abstractmethod
    async def insert(self, data: dict) -> str:
        pass

    @abstractmethod
    async def get_by_id(self, id: str) -> dict | None:
        pass

    @abstractmethod
    async def list(self, limit: int = 50, offset: int = 0) -> list:
        pass
