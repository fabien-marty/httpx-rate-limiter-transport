import asyncio
import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.limit import (
    ByHostConcurrencyRateLimit,
    GlobalConcurrencyRateLimit,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        limits=[
            # no more than 10 concurrent requests to any host (global limit)
            GlobalConcurrencyRateLimit(concurrency_limit=10),
            # no more than 1 concurrent request to any host (per host limit)
            ByHostConcurrencyRateLimit(concurrency_limit=1),
        ],
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)


async def request(n: int):
    client = get_httpx_client()
    async with client:
        futures = [client.get("https://www.google.com/") for _ in range(n)]
        res = await asyncio.gather(*futures)
        for r in res:
            print(r.status_code)


if __name__ == "__main__":
    asyncio.run(request(10))
