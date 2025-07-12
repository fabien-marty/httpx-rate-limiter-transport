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
class RateLimit:
    pass


@dataclass(kw_only=True)
class ConcurrencyRateLimit(RateLimit):
    concurrency_limit: int

    def _get_key(self, request: httpx.Request) -> str | None:
        raise NotImplementedError("get_key must be implemented")

    def __post_init__(self):
        if self.concurrency_limit <= 0:
            raise ValueError("concurrency_limit must be greater than 0")


@dataclass(kw_only=True)
class GlobalConcurrencyRateLimit(ConcurrencyRateLimit):
    def _get_key(self, request: httpx.Request) -> str | None:
        return "__global"


@dataclass(kw_only=True)
class ByHostConcurrencyRateLimit(ConcurrencyRateLimit):
    def _get_key(self, request: httpx.Request) -> str | None:
        return f"__{request.url.host}"


@dataclass(kw_only=True)
class SpecificHostConcurrencyRateLimit(ConcurrencyRateLimit):
    host: str
    fnmatch_pattern: bool = True

    def _get_key(self, request: httpx.Request) -> str | None:
        host = request.url.host
        if fnmatch.fnmatch(host, self.host):
            return f"__{host}"
        return None


@dataclass(kw_only=True)
class CustomConcurrencyRateLimit(ConcurrencyRateLimit):
    concurrency_key_hook: GetKeyHook

    def _get_key(self, request: httpx.Request) -> str | None:
        key = self.concurrency_key_hook(request)
        if key is not None and key.startswith("__"):
            raise ValueError(f"key cannot start with '__': {key}")
        return key


def get_concurrency_default_limits() -> list[ConcurrencyRateLimit]:
    return [
        GlobalConcurrencyRateLimit(concurrency_limit=100),
        ByHostConcurrencyRateLimit(concurrency_limit=10),
    ]
