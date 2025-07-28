import asyncio
import httpx
from httpx_rate_limiter_transport.limit import (
    ByHostConcurrencyRateLimit,
    GlobalConcurrencyRateLimit,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport
from async_redis_rate_limiters import DistributedSemaphoreManager


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        limits=[
            # Global limit: no more than 10 concurrent requests to any host
            GlobalConcurrencyRateLimit(concurrency_limit=10),
            # Per-host limit: no more than 1 concurrent request per host
            ByHostConcurrencyRateLimit(concurrency_limit=1),
        ],
        semaphore_manager=DistributedSemaphoreManager(
            redis_url="redis://localhost:6379", redis_ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)


async def request(n: int):
    client = get_httpx_client()
    async with client:
        # This will respect the rate limits - only 1 request per host
        # will execute concurrently, with a global max of 10
        futures = [client.get("https://www.google.com/") for _ in range(n)]
        res = await asyncio.gather(*futures)
        for r in res:
            print(r.status_code)


if __name__ == "__main__":
    # This will make 10 requests, but only 1 will execute at a time
    # due to the per-host limit
    asyncio.run(request(10))
