# httpx-rate-limiter-transport

![Python Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/python310plus.svg)
[![UV Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/uv.svg)](https://docs.astral.sh/uv/)
[![Mergify Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/mergify.svg)](https://mergify.com/)
[![Renovate Badge](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/renovate.svg)](https://docs.renovatebot.com/)
[![MIT Licensed](https://raw.githubusercontent.com/fabien-marty/common/refs/heads/main/badges/mit.svg)](https://en.wikipedia.org/wiki/MIT_License)

## What is it?

This project provides an **async transport** for [httpx](https://www.python-httpx.org/) to implement various rate limiting (using a centralized redis as backend).

![](./docs/semaphore.png)

> [!NOTE]
> You can read some details about httpx transports on [this page](https://www.python-httpx.org/advanced/transports/).

## Features

- ✅ Limit the total number of concurrent outgoing requests (to any host)
- ✅ Limit the number of concurrent requests per host
- ✅ Provide your own logic/limit
    - for example: you can limit the number of concurrent requests by HTTP method or only for some given hosts...
- ✅ TTL to avoid blocking the semaphore forever (in some special cases like computer crash or network issues at the very wrong moment)
- ✅ Can wrap another transport (if you already use one)
- ✅ Multiple limits support
- ✅ Redis backend for distributed rate limiting

## Roadmap

- [ ] Add a "request per minute" rate limiting
- [x] Multiple limits
- [x] Logging
- [ ] Sync version

## Installation

`pip install httpx-rate-limiter-transport`

*(or the same with your favorite package manager)*

## Quickstart

Here's a simple example that demonstrates the basic usage:

```python
import asyncio
import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
from httpx_rate_limiter_transport.limit import (
    ByHostConcurrencyRateLimit,
    GlobalConcurrencyRateLimit,
)
from httpx_rate_limiter_transport.transport import ConcurrencyRateLimiterTransport


def get_httpx_client() -> httpx.AsyncClient:
    transport = ConcurrencyRateLimiterTransport(
        limits=[
            # Global limit: no more than 10 concurrent requests to any host
            GlobalConcurrencyRateLimit(concurrency_limit=10),
            # Per-host limit: no more than 1 concurrent request per host
            ByHostConcurrencyRateLimit(concurrency_limit=1),
        ],
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)


async def request(n: int):
    client = get_httpx_client()
    async with client:
        # This will respect the rate limits - only 1 request per host
        # will execute concurrently, with a global max of 10
        futures = [client.get("https://www.google.com/") for _ in range(n)]
        res = await asyncio.gather(*futures)
        for r in res:
            print(r.status_code)


if __name__ == "__main__":
    # This will make 10 requests, but only 1 will execute at a time
    # due to the per-host limit
    asyncio.run(request(10))

```

**Expected behavior:** The requests will be rate-limited - only 1 request to google.com will execute at a time, even though we're trying to make 10 concurrent requests.

## How-to

<details>

<summary>How to get a concurrency limit for only one given host?</summary>

To get a concurrency limit only for a given host, you can use a `SingleHostConcurrencyRateLimit` limit object.

```python
import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
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
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)

```

</details>

<details>

<summary>How to implement your own custom logic?</summary>

You can use a `CustomConcurrencyRateLimit` object with a custom hook to implement your own logic.

If the hook returns None, this concurrency limit is deactivated. If the hook returns a key (as a string),
we count/limit the number of concurrent requests per distinct key.

```python
import httpx
from httpx_rate_limiter_transport.backend.adapters.redis import (
    RedisRateLimiterBackendAdapter,
)
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
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
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
        backend_adapter=RedisRateLimiterBackendAdapter(
            redis_url="redis://localhost:6379", ttl=300
        ),
    )
    return httpx.AsyncClient(transport=transport, timeout=300)

```

</details>

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. For major changes, please open an issue first to discuss what you would like to change.

### Development Setup

1. Fork the repository
2. Create a feature branch
3. Install development dependencies: `make sync`
4. Run lint: `make lint`
5. Run tests: `make test`
6. Submit a pull request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.