from dataclasses import dataclass
import time
from typing import AsyncContextManager
import uuid

from httpx_rate_limiter_transport.backend.interface import (
    DEFAULT_TTL,
    RateLimiterBackendAdapter,
    RateLimiterTimeoutError,
)
import redis.asyncio as redis

ACQUIRE_LUA_SCRIPT = """
local key = KEYS[1]
local client_id = ARGV[1]
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local expires_at = now + ttl
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
redis.call('ZADD', key, expires_at, client_id)
redis.call('EXPIRE', key, ttl + 10)
local card = redis.call('ZCARD', key)
if card <= limit then
    return 1
else
    redis.call('ZREM', key, client_id)
    return 0
end
"""

RELEASE_LUA_SCRIPT = """
local key = KEYS[1]
local list_key = KEYS[2]
local client_id = ARGV[1]
local ttl = tonumber(ARGV[2])
local removed = redis.call('ZREM', key, client_id)
if removed == 1 then
    redis.call('LPUSH', list_key, 1)
    redis.call('EXPIRE', list_key, ttl + 10)
end
return removed
"""


@dataclass(kw_only=True)
class RedisSemaphore:
    redis_url: str
    key: str
    value: int
    ttl: int

    __client_id: str | None = None
    __pool: redis.ConnectionPool | None = None

    @property
    def _pool(self) -> redis.ConnectionPool:
        if self.__pool is None:
            self.__pool = redis.ConnectionPool.from_url(self.redis_url)
        return self.__pool

    def _get_client(self) -> redis.Redis:
        return redis.Redis(connection_pool=self._pool)

    def _get_list_key(self) -> str:
        return f"rate_limiter:list:{self.key}"

    def _get_zset_key(self) -> str:
        return f"rate_limiter:zset:{self.key}"

    async def __aenter__(self) -> None:
        client_id = str(uuid.uuid4()).replace("-", "")
        client = self._get_client()
        acquire_script = client.register_script(ACQUIRE_LUA_SCRIPT)
        async with client:
            start = int(time.perf_counter())
            while True:
                now = int(time.perf_counter())
                acquired = await acquire_script(
                    keys=[self._get_zset_key()],
                    args=[client_id, self.value, self.ttl, now],
                )
                if acquired == 1:
                    self.__client_id = client_id
                    tmp = await client.zrange(self._get_zset_key(), 0, -1)
                    print(len(tmp), tmp)
                    return None
                if now - start >= self.ttl:
                    raise RateLimiterTimeoutError()
                await client.blpop(keys=[self._get_list_key()], timeout=10)  # type: ignore

    async def __aexit__(self, exc_type, exc_value, traceback):
        assert self.__client_id is not None
        client = self._get_client()
        release_script = client.register_script(RELEASE_LUA_SCRIPT)
        async with client:
            await release_script(
                keys=[self._get_zset_key(), self._get_list_key()],
                args=[self.__client_id, self.ttl],
            )


@dataclass
class RedisRateLimiterBackendAdapter(RateLimiterBackendAdapter):
    redis_url: str = "redis://localhost:6379"
    ttl: int = DEFAULT_TTL

    def semaphore(self, key: str, value: int) -> AsyncContextManager[None]:
        return RedisSemaphore(
            redis_url=self.redis_url, key=key, value=value, ttl=self.ttl
        )
