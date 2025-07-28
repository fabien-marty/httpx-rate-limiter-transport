import asyncio
import time
from async_redis_rate_limiters import DistributedSemaphoreManager
import httpx

from httpx_rate_limiter_transport.limit import GlobalConcurrencyRateLimit
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport

counter_dict = {"counter": 0}

NUMBER_OF_REQUESTS = 1000
MAX_CONCURRENCY = 10


async def request(client: httpx.AsyncClient):
    res = await client.get("http://foobar.com/")
    assert res.status_code == 200


async def mock_handler(request: httpx.Request) -> httpx.Response:
    global counter_dict
    counter_dict["counter"] += 1
    if counter_dict["counter"] > MAX_CONCURRENCY:
        raise Exception(f"Counter is greater than {max}")
    await asyncio.sleep(0.001)
    counter_dict["counter"] -= 1
    return httpx.Response(status_code=200, content=b"Hello, world!")


async def main():
    transport = ConcurrencyRateLimiterTransport(
        limits=[
            # Global limit: no more than 10 concurrent requests to any host
            GlobalConcurrencyRateLimit(concurrency_limit=MAX_CONCURRENCY),
        ],
        semaphore_manager=DistributedSemaphoreManager(
            redis_url="redis://localhost:6379", redis_ttl=300
        ),
        inner_transport=httpx.MockTransport(mock_handler),
    )
    client = httpx.AsyncClient(transport=transport)
    async with client:
        before = time.perf_counter()
        tasks = [request(client) for _ in range(NUMBER_OF_REQUESTS)]
        await asyncio.gather(*tasks)
        after = time.perf_counter()
        print(f"Time taken: {after - before} seconds")


if __name__ == "__main__":
    asyncio.run(main())
