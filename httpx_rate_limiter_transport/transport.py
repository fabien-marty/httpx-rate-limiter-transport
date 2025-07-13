import contextlib
from dataclasses import dataclass, field
import logging
import time
from types import TracebackType
import httpx
from typing import Protocol, Sequence

import stlog

from httpx_rate_limiter_transport.backend.interface import RateLimiterBackendAdapter
from httpx_rate_limiter_transport.limit import (
    ConcurrencyRateLimit,
    get_concurrency_default_limits,
)

DEFAULT_MAX_CONCURRENCY = 100


@dataclass
class ConcurrencyRateLimiterMetrics:
    concurrency_waiting_time: float = 0.0
    """Total time (in seconds) spent waiting for concurrency semaphores."""

    total_call_time: float = 0.0
    """Total time (in seconds) spent waiting in the transport (including concurrency
    semaphore waiting time and inner transport call time).
    """


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
    limits: Sequence[ConcurrencyRateLimit] = field(
        default_factory=get_concurrency_default_limits
    )
    """
    The limits to apply to apply.

    Defaults to  [
        ByHostConcurrencyRateLimit(concurrency_limit=10),
        GlobalConcurrencyRateLimit(concurrency_limit=100),
    ]

    WARNING: don't mix different limits in different transports for the same redis instance/namespace
    to avoid deadlocks!
    """

    push_metrics_hook: PushMetricsHook | None = None
    """
    A hook to be called with some metrics (if defined).
    """

    logger: logging.LoggerAdapter | None = field(
        default_factory=lambda: stlog.getLogger("httpx-rate_limiter_transport")
    )
    """The structured logger to use for logging.

    Set it to `None` to disable logging.
    """

    async def handle_async_request(
        self,
        request: httpx.Request,
    ) -> httpx.Response:
        before = time.perf_counter()
        async with contextlib.AsyncExitStack() as stack:
            for limit in self.limits:
                key = limit._get_key(request)
                if key is None:
                    continue
                semaphore = self.backend_adapter.semaphore(key, limit.concurrency_limit)
                if self.logger:
                    self.logger.debug(
                        f"Acquiring {type(limit).__name__} semaphore...",
                        key=key,
                        limit=limit.concurrency_limit,
                    )
                await stack.enter_async_context(semaphore)
                if self.logger:
                    self.logger.debug(
                        f"Semaphore {type(limit).__name__} acquired.",
                        key=key,
                        limit=limit.concurrency_limit,
                    )
            after_semaphores = time.perf_counter()
            res = await self.inner_transport.handle_async_request(request)
            after = time.perf_counter()
            if self.push_metrics_hook:
                await self.push_metrics_hook(
                    ConcurrencyRateLimiterMetrics(
                        concurrency_waiting_time=after_semaphores - before,
                        total_call_time=after - before,
                    )
                )
            return res
        raise Exception("should not happen")  # only for mypy
