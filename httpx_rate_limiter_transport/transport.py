import contextlib
from dataclasses import dataclass, field
import time
from types import TracebackType
import httpx
from typing import Protocol

from httpx_rate_limiter_transport.backend.interface import RateLimiterBackendAdapter

DEFAULT_MAX_CONCURRENCY = 100


@dataclass
class ConcurrencyRateLimiterMetrics:
    semaphore_waiting_time: float = 0.0


class GetKeyHook(Protocol):
    def __call__(self, request: httpx.Request) -> str | None: ...


class GetConcurrencyHook(Protocol):
    def __call__(self, request: httpx.Request) -> int | None: ...


class PushMetricsHook(Protocol):
    async def __call__(self, metrics: ConcurrencyRateLimiterMetrics) -> None: ...


@dataclass
class _RateLimiterTransport(httpx.AsyncBaseTransport):
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


@dataclass
class ConcurrencyRateLimiterTransport(_RateLimiterTransport):
    global_concurrency: int | None = DEFAULT_MAX_CONCURRENCY
    """
    The maximum number of concurrent requests to all hosts.
    If None, no global concurrency limit is applied. In that case, you should have
    defined get_concurrency_cb() and/or get_key_cb() to provide a custom logic.
    """

    get_concurrency_hook: GetConcurrencyHook | None = None
    """
    A hook to get the number of concurrent requests for a given request.
    If None, no concurrency limit is applied (in addition to the global limit).

    If the given hook returns None or 0 for a given request, no concurrency limit is applied
    (in addition to the global limit) for this specific request.
    """

    get_key_hook: GetKeyHook | None = None
    """
    A hook to get the rate limiting key for a given request.
    If None, we use the DEFAULT_MAX_CONCURRENCY value as limit.

    If the given hook returns None or 0 for a given request, no concurrency limit is applied
    (in addition to the global limit) for this specific request.
    """

    push_metrics_hook: PushMetricsHook | None = None
    """
    A hook to be called with some metrics (if defined).
    """

    def _get_key(self, request: httpx.Request) -> str | None:
        if self.get_key_hook is None:
            return None
        key = self.get_key_hook(request)
        if key is not None and key.startswith("__"):
            raise ValueError(f"key cannot start with '__': {key}")
        return key

    def _get_concurrency(self, request: httpx.Request) -> int | None:
        if self.get_concurrency_hook is None:
            return DEFAULT_MAX_CONCURRENCY
        concurrency = self.get_concurrency_hook(request)
        if (
            concurrency is not None
            and self.global_concurrency is not None
            and concurrency > self.global_concurrency
        ):
            raise ValueError(
                f"max_concurrency ({concurrency}) is greater than global_concurrency ({self.global_concurrency})"
            )
        return concurrency

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        before = time.perf_counter()
        key = self._get_key(request)
        concurrency = self._get_concurrency(request)
        async with contextlib.AsyncExitStack() as stack:
            if self.global_concurrency:
                global_semaphore = self.backend_adapter.semaphore(
                    "__global", self.global_concurrency
                )
                await stack.enter_async_context(global_semaphore)
            if concurrency and key:
                semaphore = self.backend_adapter.semaphore(key, concurrency)
                await stack.enter_async_context(semaphore)
            after = time.perf_counter()
            res = await self.inner_transport.handle_async_request(request)
            if self.push_metrics_hook:
                await self.push_metrics_hook(
                    ConcurrencyRateLimiterMetrics(semaphore_waiting_time=after - before)
                )
            return res
        raise Exception("should not happen")  # only for mypy
