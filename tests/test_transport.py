import asyncio
from dataclasses import dataclass, field
import time
import uuid
import httpx

from httpx_rate_limiter_transport.backend.adapters.memory import (
    MemoryRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.limit import GlobalConcurrencyRateLimit
from httpx_rate_limiter_transport.transport import (
    ConcurrencyRateLimiterMetrics,
    ConcurrencyRateLimiterTransport,
)


@dataclass
class AsyncMockTransport(httpx.AsyncBaseTransport):
    max_concurrency: int
    wait_time: float
    clients: dict[str, bool] = field(default_factory=dict)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        client_id = str(uuid.uuid4()).replace("-", "")
        self.clients[client_id] = True
        if len(self.clients) > self.max_concurrency:
            raise Exception("too many concurrent requests")
        await asyncio.sleep(self.wait_time)
        self.clients.pop(client_id)
        return httpx.Response(status_code=200)


async def test_semaphore():
    mock = AsyncMockTransport(max_concurrency=10, wait_time=1)
    transport = ConcurrencyRateLimiterTransport(
        limits=[GlobalConcurrencyRateLimit(concurrency_limit=10)],
        inner_transport=mock,
        backend_adapter=MemoryRateLimiterBackendAdapter(ttl=10),
    )
    client = httpx.AsyncClient(transport=transport)
    before = time.perf_counter()
    async with client:
        futures = [client.get("http://foo.com/bar") for _ in range(20)]
        await asyncio.gather(*futures)
    after = time.perf_counter()
    assert after - before > 2.0
    assert after - before < 3.0


async def test_metrics():
    async def push_metrics_hook(metrics: ConcurrencyRateLimiterMetrics):
        assert metrics.concurrency_waiting_time > 0.0
        assert metrics.total_call_time > 0.0

    mock = AsyncMockTransport(max_concurrency=10, wait_time=1)
    transport = ConcurrencyRateLimiterTransport(
        limits=[GlobalConcurrencyRateLimit(concurrency_limit=10)],
        inner_transport=mock,
        backend_adapter=MemoryRateLimiterBackendAdapter(ttl=10),
        push_metrics_hook=push_metrics_hook,
    )
    client = httpx.AsyncClient(transport=transport)
    async with client:
        await client.get("http://foo.com/bar")
