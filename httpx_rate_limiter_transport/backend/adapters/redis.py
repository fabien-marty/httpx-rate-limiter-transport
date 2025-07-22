import asyncio
from dataclasses import dataclass
import os
import time
from typing import AsyncContextManager
import uuid

from httpx_rate_limiter_transport.backend.interface import (
    DEFAULT_TTL,
    RateLimiterBackendAdapter,
)
import redis.asyncio as redis

DEFAULT_REDIS_HOST = os.environ.get("DEFAULT_REDIS_HOST", "localhost")
DEFAULT_REDIS_PORT = int(os.environ.get("DEFAULT_REDIS_PORT", "6379"))

ACQUIRE_LUA_SCRIPT = """
local key = KEYS[1]
local list_key = KEYS[2]
local client_id = ARGV[1]
local limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local now = tonumber(ARGV[4])
local expires_at = now + ttl
local cleaned = redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if cleaned > 0 then
    redis.call('LPUSH', list_key, 1)
    redis.call('EXPIRE', list_key, ttl + 10)
end
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
class _RedisSemaphore:
    namespace: str
    redis_url: str
    key: str
    value: int
    ttl: int
    _pool_acquire: redis.ConnectionPool
    _pool_release: redis.ConnectionPool
    _blocking_wait_time: int = 10
    __client_id: str | None = None

    def _get_client(self, pool: redis.ConnectionPool) -> redis.Redis:
        return redis.Redis(connection_pool=pool)

    def _get_list_key(self) -> str:
        return f"{self.namespace}:rate_limiter:list:{self.key}"

    def _get_zset_key(self) -> str:
        return f"{self.namespace}:rate_limiter:zset:{self.key}"

    async def __aenter__(self) -> None:
        if self.__client_id is not None:
            raise RuntimeError(
                "Semaphore already acquired (in the past) => don't reuse the same semaphore instance"
            )
        client_id = str(uuid.uuid4()).replace("-", "")
        client = self._get_client(self._pool_acquire)
        acquire_script = client.register_script(ACQUIRE_LUA_SCRIPT)
        async with client:
            while True:
                try:
                    now = time.time()
                    acquired = await acquire_script(
                        keys=[self._get_zset_key(), self._get_list_key()],
                        args=[client_id, self.value, self.ttl, now],
                    )
                    if acquired == 1:
                        self.__client_id = client_id
                        return None
                    await client.blpop(
                        keys=[self._get_list_key()], timeout=self._blocking_wait_time
                    )  # type: ignore
                except redis.ConnectionError as e:
                    if "Too many connections" in str(e):
                        print("sleep 0.1")
                        await asyncio.sleep(0.1)
                    else:
                        raise e

    async def __aexit__(self, exc_type, exc_value, traceback):
        assert self.__client_id is not None
        client = await self._get_client(self._pool_release)
        release_script = client.register_script(RELEASE_LUA_SCRIPT)
        while True:
            async with client:
                try:
                    await release_script(
                        keys=[self._get_zset_key(), self._get_list_key()],
                        args=[self.__client_id, self.ttl],
                    )
                    return
                except redis.ConnectionError as e:
                    if "Too many connections" in str(e):
                        print("sleep 1")
                        await asyncio.sleep(0.1)
                    else:
                        raise e


@dataclass
class RedisRateLimiterBackendAdapter(RateLimiterBackendAdapter):
    """Redis-based backend adapter for rate limiting.

    This adapter uses Redis as a centralized backend to implement distributed
    rate limiting across multiple processes or machines.
    """

    namespace: str = "default"
    """Redis namespace prefix for all keys to avoid conflicts with other applications."""

    redis_url: str = f"redis://{DEFAULT_REDIS_HOST}:{DEFAULT_REDIS_PORT}"
    """Redis connection URL in the format redis://host:port or redis://host:port/db.
    
    See redis-py project for more details.
    
    """

    ttl: int = DEFAULT_TTL
    """Time-to-live in seconds for semaphore entries to prevent deadlocks in case of crashes."""

    _blocking_wait_time: int = 10
    """Maximum time in seconds to wait for a semaphore release notification.

    Only for testing purposes.
    """

    __pool_acquire: redis.ConnectionPool | None = None
    __pool_release: redis.ConnectionPool | None = None

    @property
    def _pool_acquire(self) -> redis.ConnectionPool:
        if self.__pool_acquire is None:
            self.__pool_acquire = redis.ConnectionPool.from_url(
                self.redis_url, max_connections=1000
            )
        return self.__pool_acquire

    @property
    def _pool_release(self) -> redis.ConnectionPool:
        if self.__pool_release is None:
            self.__pool_release = redis.ConnectionPool.from_url(
                self.redis_url, max_connections=1000
            )
        return self.__pool_release

    def semaphore(self, key: str, value: int) -> AsyncContextManager[None]:
        return _RedisSemaphore(
            namespace=self.namespace,
            redis_url=self.redis_url,
            key=key,
            value=value,
            ttl=self.ttl,
            _pool_acquire=self._pool_acquire,
            _pool_release=self._pool_release,
            _blocking_wait_time=self._blocking_wait_time,
        )
