# httpx-rate-limiter-transport

![Python Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/python310plus.svg)
[![UV Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/uv.svg)](https://docs.astral.sh/uv/)
[![Mergify Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/mergify.svg)](https://mergify.com/)
[![Renovate Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/renovate.svg)](https://docs.renovatebot.com/)
[![MIT Licensed](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/mit.svg)](https://en.wikipedia.org/wiki/MIT_License)

## What is it?

This project provides an async transport for [httpx](https://www.python-httpx.org/) to implement various rate limiting (using a centralized redis as backend).

![](./docs/semaphore.png)

## Features

- Global semaphore to limit the number of concurrent requests to all hosts
- Optional second level of semaphore to limit the number of concurrent requests (you can provide your own logic)
    - for example: you can limit the number of concurrent requests by host, by HTTP method or only for some given hosts...
- TTL to avoid blocking the semaphore forever (in some special cases like computer crash or network issues at the very wrong moment)
- Can wrap another transport (if you already use one)

## Roadmap

- [ ] Add a "request per minute" rate limiting

## Installation

`pip install httpx-rate-limiter-transport`

## Quickstart

```python
import asyncio
import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        global_concurrency=2,
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)


async def request(n: int):
    client = get_httpx_client()
    async with client:
        futures = [client.get("https://www.google.com/") for _ in range(n)]
        res = await asyncio.gather(*futures)
        for r in res:
            print(r.status_code)


if __name__ == "__main__":
    asyncio.run(request(10))

```

## How-to

<details>

<summary>How to get a concurrency limit by host?</summary>

To get a "concurrency limit by host", you can provide 2 hooks to define a custom/second level of concurrency limit.

```python
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

```

</details>

<details>

<summary>How to get a concurrency limit for only one given host?</summary>

To get a concurrency limit only for a given host, you can return `None` from your custom hooks to deactivate the
concurrency control for this specific request.

```python
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

```

</details>

<details>

<summary>How to wrap another httpx transport?</summary>

If you already use a specific `httpx` transport, you can wrap it inside this one.

```python
import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_httpx_client() -> httpx.AsyncClient:
    original_transport = httpx.AsyncHTTPTransport(retries=3)
    transport = ConcurrencyRateLimiterTransport(
        inner_transport=original_transport,  # let's wrap the original transport
        global_concurrency=10,
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)

```

</details>