import asyncio
import time
import uuid
import pytest
import redis

from httpx_rate_limiter_transport.backend.adapters.memory import (
    MemoryRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.backend.adapters.redis import (
    DEFAULT_REDIS_HOST,
    DEFAULT_REDIS_PORT,
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.backend.interface import (
    RateLimiterBackendAdapter,
)


def is_redis_available() -> bool:
    try:
        r = redis.Redis(host=DEFAULT_REDIS_HOST, port=DEFAULT_REDIS_PORT)
        r.ping()
        return True
    except Exception:
        return False


async def acquire_semaphore(
    acquired: dict[str, bool] | None,
    backend: RateLimiterBackendAdapter,
    key: str,
    value: int,
    duration: int,
):
    client_id = str(uuid.uuid4()).replace("-", "")
    async with backend.semaphore(key, value):
        if acquired is not None:
            acquired[client_id] = True
            if len(acquired) > value:
                raise Exception("too many clients")
        await asyncio.sleep(duration)
        if acquired is not None:
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


async def _test_timeout(backend: RateLimiterBackendAdapter):
    assert backend.ttl == 1
    # This 3s task will acquire the semaphore
    # (but it will timeout)
    task = asyncio.create_task(acquire_semaphore(None, backend, "test1", 1, 3))
    await asyncio.sleep(0.5)
    before = time.perf_counter()
    await acquire_semaphore(None, backend, "test1", 1, 1)
    after = time.perf_counter()
    assert after - before > 0.5
    assert after - before < 3.0
    await task


@pytest.mark.skipif(not is_redis_available(), reason="redis is not available")
async def test_redis_backend():
    backend = RedisRateLimiterBackendAdapter(ttl=10)
    await _test_backend(backend)


async def test_memory_backend():
    backend = MemoryRateLimiterBackendAdapter(ttl=10)
    await _test_backend(backend)


@pytest.mark.skipif(not is_redis_available(), reason="redis is not available")
async def test_timeout_redis_backend():
    backend = RedisRateLimiterBackendAdapter(ttl=1, _blocking_wait_time=1)
    await _test_timeout(backend)


async def test_timeout_memory_backend():
    backend = MemoryRateLimiterBackendAdapter(ttl=1)
    await _test_timeout(backend)
