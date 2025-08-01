from async_redis_rate_limiters import DistributedSemaphoreManager
import httpx
from httpx_rate_limiter_transport.limit import CustomConcurrencyRateLimit
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def concurrency_key_hook(request: httpx.Request) -> str | None:
    if request.url.host == "www.foobar.com" and request.method == "POST":
        return "post on www.foobar.com"
    return None  # no concurrency limit


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        limits=[
            CustomConcurrencyRateLimit(
                concurrency_limit=10, concurrency_key_hook=concurrency_key_hook
            )
        ],
        semaphore_manager=DistributedSemaphoreManager(
            redis_url="redis://localhost:6379", redis_ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)
