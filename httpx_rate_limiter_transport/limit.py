import fnmatch
from typing import Protocol
from dataclasses import dataclass
import httpx


class GetKeyHook(Protocol):
    """Defines a get_key hook (callable).

    If the hook returns None for the given request, no rate limit is applied.
    Key starting with double underscores are reserved and must not be returned.

    """

    def __call__(self, request: httpx.Request) -> str | None: ...


@dataclass(kw_only=True)
class _RateLimit:
    """Base class for rate limits."""


@dataclass(kw_only=True)
class ConcurrencyRateLimit(_RateLimit):
    """Base class for concurrency rate limits."""

    concurrency_limit: int
    """Maximum number of concurrent requests for this limit."""

    def _get_key(self, request: httpx.Request) -> str | None:
        raise NotImplementedError("get_key must be implemented")

    def __post_init__(self):
        if self.concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be greater than 0")


@dataclass(kw_only=True)
class GlobalConcurrencyRateLimit(ConcurrencyRateLimit):
    """Global concurrency rate limit.

    Limit the number of concurrent requests for all outgoing requests.

    """

    def _get_key(self, request: httpx.Request) -> str | None:
        return "__global"


@dataclass(kw_only=True)
class ByHostConcurrencyRateLimit(ConcurrencyRateLimit):
    """Concurrency rate limit by host.

    Limit the number of concurrent requests for all outgoing requests to the same host.

    """

    def _get_key(self, request: httpx.Request) -> str | None:
        return f"__{request.url.host}"


@dataclass(kw_only=True)
class SingleHostConcurrencyRateLimit(ConcurrencyRateLimit):
    """Concurrency rate limit for a single/specific host.

    Limit the number of concurrent requests for all outgoing requests to a given/specific host.

    fnmatch patterns are supported. Example: host="*.foobar.com" will match all subdomains of foobar.com.

    """

    host: str
    fnmatch_pattern: bool = True
    """Whether to use fnmatch pattern to match the host."""

    def _get_key(self, request: httpx.Request) -> str | None:
        host = request.url.host
        if self.fnmatch_pattern:
            if fnmatch.fnmatch(host, self.host):
                return f"__{host}"
        else:
            if host == self.host:
                return f"__{host}"
        return None


@dataclass(kw_only=True)
class CustomConcurrencyRateLimit(ConcurrencyRateLimit):
    """Custom concurrency rate limit.

    Limit the number of concurrent requests for all outgoing requests based on a custom key.
    You have to provide a hook to create the key from the request with your own logic.

    """

    concurrency_key_hook: GetKeyHook

    def _get_key(self, request: httpx.Request) -> str | None:
        key = self.concurrency_key_hook(request)
        if key is not None and key.startswith("__"):
            raise ValueError(f"key cannot start with '__': {key}")
        return key


def get_concurrency_default_limits() -> list[ConcurrencyRateLimit]:
    """Get the default concurrency rate limits."""
    return [
        ByHostConcurrencyRateLimit(concurrency_limit=10),
        GlobalConcurrencyRateLimit(concurrency_limit=100),
    ]
