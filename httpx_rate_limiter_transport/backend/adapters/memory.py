import asyncio
from dataclasses import dataclass, field
from typing import AsyncContextManager

from httpx_rate_limiter_transport.backend.interface import (
    RateLimiterBackendAdapter,
)


@dataclass(kw_only=True)
class _SemaphoreWithTTL:
    ttl: int
    _semaphore: asyncio.Semaphore
    _task: asyncio.Task | None = None

    async def __aenter__(self) -> None:
        self._task = asyncio.create_task(self._auto_release())
        await self._semaphore.__aenter__()

    async def _auto_release(self) -> None:
        await asyncio.sleep(self.ttl)
        await self._semaphore.__aexit__(None, None, None)

    async def __aexit__(self, exc_type, exc_value, traceback):
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._semaphore.locked():
            await self._semaphore.__aexit__(exc_type, exc_value, traceback)


@dataclass
class MemoryRateLimiterBackendAdapter(RateLimiterBackendAdapter):
    _semaphores: dict[tuple[str, int], asyncio.Semaphore] = field(default_factory=dict)

    def get_semaphore(self, key: str, value: int) -> asyncio.Semaphore:
        if (key, value) not in self._semaphores:
            self._semaphores[(key, value)] = asyncio.Semaphore(value)
        return self._semaphores[(key, value)]

    def semaphore(self, key: str, value: int) -> AsyncContextManager[None]:
        sem = self.get_semaphore(key, value)
        return _SemaphoreWithTTL(_semaphore=sem, ttl=self.ttl)
