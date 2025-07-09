import asyncio
import time
import uuid
import pytest
import redis

from httpx_rate_limiter_transport.backend.adapters.memory import (
    MemoryRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.backend.interface import RateLimiterBackendAdapter


def is_redis_available() -> bool:
    try:
        r = redis.Redis(host="localhost", port=6379, db=0)
        r.ping()
        return True
    except Exception:
        return False


async def acquire_semaphore(
    acquired: dict[str, bool],
    backend: RateLimiterBackendAdapter,
    key: str,
    value: int,
    duration: int,
):
    client_id = str(uuid.uuid4()).replace("-", "")
    async with backend.semaphore(key, value):
        acquired[client_id] = True
        if len(acquired) > value:
            print(len(acquired), acquired)
            raise Exception("too many clients")
        await asyncio.sleep(duration)
        acquired.pop(client_id)


async def _test_backend(backend: RateLimiterBackendAdapter):
    acquired: dict[str, bool] = {}
    before = time.perf_counter()
    acquire_futures = [
        acquire_semaphore(acquired, backend, "test2", 10, 1) for x in range(20)
    ]
    await asyncio.gather(*acquire_futures)
    after = time.perf_counter()
    assert after - before > 2.0
    assert after - before < 3.0


@pytest.mark.skipif(not is_redis_available(), reason="redis is not available")
async def test_redis_backend():
    backend = RedisRateLimiterBackendAdapter(ttl=10)
    await _test_backend(backend)


async def test_memory_backend():
    backend = MemoryRateLimiterBackendAdapter(ttl=10)
    await _test_backend(backend)
