from abc import ABC, abstractmethod

from dataclasses import dataclass
from typing import AsyncContextManager


DEFAULT_TTL = 300  # 5 minutes (300 seconds)


@dataclass
class RateLimiterContextManager:
    value: int

    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc_value, traceback):
        pass


@dataclass
class RateLimiterBackendAdapter(ABC):
    ttl: int = DEFAULT_TTL

    @abstractmethod
    def semaphore(self, key: str, value: int) -> AsyncContextManager[None]:
        return RateLimiterContextManager(value)
