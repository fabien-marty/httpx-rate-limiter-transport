from dataclasses import dataclass, field
from types import TracebackType
import httpx
from typing import Protocol

from httpx_rate_limiter_transport.backend.interface import RateLimiterBackendAdapter

DEFAULT_MAX_CONCURRENCY = 10


class KeyBuilder(Protocol):
    def __call__(self, request: httpx.Request) -> str: ...


class ConcurrencyBuilder(Protocol):
    def __call__(self, request: httpx.Request) -> int: ...


@dataclass
class RateLimiterTransport(httpx.AsyncBaseTransport):
    backend_adapter: RateLimiterBackendAdapter
    inner_transport: httpx.AsyncBaseTransport = field(
        default_factory=httpx.AsyncHTTPTransport
    )

    async def __aenter__(self):
        return await self.inner_transport.__aenter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None = None,
        exc_value: BaseException | None = None,
        traceback: TracebackType | None = None,
    ) -> None:
        await self.inner_transport.__aexit__(exc_type, exc_value, traceback)


def get_host_key(request: httpx.Request) -> str:
    return request.url.host


def get_default_concurrency(request: httpx.Request) -> int:
    return DEFAULT_MAX_CONCURRENCY


@dataclass
class ConcurrencyRateLimiterTransport(RateLimiterTransport):
    get_concurrency: ConcurrencyBuilder = field(
        default_factory=lambda: get_default_concurrency
    )
    get_key: KeyBuilder = field(default_factory=lambda: get_host_key)

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        key = self.get_key(request)
        max_concurrency = self.get_concurrency(request)
        semaphore = self.backend_adapter.semaphore(key, max_concurrency)
        async with semaphore:
            return await self.inner_transport.handle_async_request(request)
