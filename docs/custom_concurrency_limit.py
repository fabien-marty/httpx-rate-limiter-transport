import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        global_concurrency=100,  # global concurrency limit (for all requests)
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
        get_concurrency_hook=lambda request: 10,  # set a second level of concurrency limit of 10
        get_key_hook=lambda request: request.url.host,  # use the host as key for the second level of concurrency limit
    )
    return httpx.AsyncClient(transport=transport, timeout=300)
