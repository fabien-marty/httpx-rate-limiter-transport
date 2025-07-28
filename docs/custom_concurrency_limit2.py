from async_redis_rate_limiters import DistributedSemaphoreManager
import httpx
from httpx_rate_limiter_transport.limit import (
    SingleHostConcurrencyRateLimit,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        limits=[
            # Limit the number of concurrent requests to 10 for any host matching *.foobar.com
            SingleHostConcurrencyRateLimit(
                concurrency_limit=10, host="*.foobar.com", fnmatch_pattern=True
            ),
        ],
        semaphore_manager=DistributedSemaphoreManager(
            redis_url="redis://localhost:6379", redis_ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)
