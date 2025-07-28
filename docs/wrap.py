import httpx
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport
from async_redis_rate_limiters import DistributedSemaphoreManager


def get_httpx_client() -> httpx.AsyncClient:
    original_transport = httpx.AsyncHTTPTransport(retries=3)
    transport = ConcurrencyRateLimiterTransport(
        inner_transport=original_transport,  # let's wrap the original transport
        semaphore_manager=DistributedSemaphoreManager(
            redis_url="redis://localhost:6379", redis_ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)
