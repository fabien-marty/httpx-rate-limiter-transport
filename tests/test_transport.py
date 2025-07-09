import asyncio
from dataclasses import dataclass, field
import time
import uuid
import httpx

from httpx_rate_limiter_transport.backend.adapters.memory import (
    MemoryRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


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
        inner_transport=mock,
        get_concurrency=lambda _: 10,
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
