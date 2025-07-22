# test the redis rate limiter backend adapter

import asyncio
import time
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)

adapter = RedisRateLimiterBackendAdapter(
    namespace="test",
    redis_url="redis://localhost:6379",
    ttl=3600,
)


async def acquire_semaphore(key: str, value: int):
    async with adapter.semaphore(key, value):
        pass


async def bench_redis_rate_limiter_backend_adapter(
    number_of_semaphores: int,
    number_of_acquires_per_semaphore: int,
    semaphore_value: int,
):
    keys = [f"key-{i}" for i in range(number_of_semaphores)]
    before = time.perf_counter()
    tasks = [
        acquire_semaphore(key, semaphore_value)
        for _ in range(number_of_acquires_per_semaphore)
        for key in keys
    ]
    print(f"{len(tasks)} tasks launched")
    await asyncio.gather(*tasks)
    after = time.perf_counter()
    print(f"Time taken: {after - before} seconds")


if __name__ == "__main__":
    asyncio.run(bench_redis_rate_limiter_backend_adapter(10, 1_000, 5))
