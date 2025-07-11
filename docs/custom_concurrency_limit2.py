import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_key_cb(request: httpx.Request) -> str | None:
    return request.url.host


def get_concurrency_cb(request: httpx.Request) -> int | None:
    host = request.url.host
    if host == "www.foobar.com":
        return 10
    return None  # no concurrency limit


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        global_concurrency=None,  # No global concurrency limit
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
        get_concurrency_hook=get_concurrency_cb,
        get_key_hook=get_key_cb,
    )
    return httpx.AsyncClient(transport=transport, timeout=300)
