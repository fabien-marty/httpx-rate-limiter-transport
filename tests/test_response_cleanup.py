import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx
import pytest

from httpx_rate_limiter_transport.limit import GlobalConcurrencyRateLimit
from httpx_rate_limiter_transport.transport import (
    ConcurrencyRateLimiterMetrics,
    ConcurrencyRateLimiterTransport,
)


@dataclass
class _Body(httpx.AsyncByteStream):
    close_started: asyncio.Event = field(default_factory=asyncio.Event)
    close_allowed: asyncio.Event = field(default_factory=asyncio.Event)
    closed: asyncio.Event = field(default_factory=asyncio.Event)

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"ok"

    async def aclose(self) -> None:
        self.close_started.set()
        await self.close_allowed.wait()
        self.closed.set()


class _FailingBody(_Body):
    async def aclose(self) -> None:
        self.close_started.set()
        raise OSError("response close failed")


@dataclass
class _ResponseTransport(httpx.AsyncBaseTransport):
    body: _Body = field(default_factory=_Body)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=self.body, request=request)


@dataclass
class _SemaphoreManager:
    release_started: asyncio.Event = field(default_factory=asyncio.Event)
    release_allowed: asyncio.Event = field(default_factory=asyncio.Event)
    released: asyncio.Event = field(default_factory=asyncio.Event)
    fail_on_release: bool = False

    @contextlib.asynccontextmanager
    async def get_semaphore(self, key: str, value: int) -> AsyncIterator[None]:
        try:
            yield
        finally:
            self.release_started.set()
            await self.release_allowed.wait()
            self.released.set()
            if self.fail_on_release:
                raise RuntimeError("semaphore release failed")


def _transport(
    inner: _ResponseTransport, semaphores: _SemaphoreManager
) -> ConcurrencyRateLimiterTransport:
    return ConcurrencyRateLimiterTransport(
        limits=[GlobalConcurrencyRateLimit(concurrency_limit=1)],
        semaphore_manager=semaphores,
        inner_transport=inner,
        logger=None,
    )


async def test_cancellation_during_semaphore_release_closes_response():
    inner = _ResponseTransport()
    inner.body.close_allowed.set()
    semaphores = _SemaphoreManager()
    task = asyncio.create_task(
        _transport(inner, semaphores).handle_async_request(
            httpx.Request("GET", "https://example.com/")
        )
    )

    try:
        await asyncio.wait_for(semaphores.release_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert inner.body.closed.is_set()
    finally:
        semaphores.release_allowed.set()
        await asyncio.wait_for(semaphores.released.wait(), timeout=1)


async def test_response_returned_to_caller_is_not_closed():
    inner = _ResponseTransport()
    inner.body.close_allowed.set()
    semaphores = _SemaphoreManager()
    semaphores.release_allowed.set()

    response = await _transport(inner, semaphores).handle_async_request(
        httpx.Request("GET", "https://example.com/")
    )

    assert not inner.body.closed.is_set()
    assert await response.aread() == b"ok"
    assert inner.body.closed.is_set()


async def test_metrics_hook_error_closes_response():
    inner = _ResponseTransport()
    inner.body.close_allowed.set()
    semaphores = _SemaphoreManager()
    semaphores.release_allowed.set()
    transport = _transport(inner, semaphores)

    async def fail_metrics(metrics: ConcurrencyRateLimiterMetrics) -> None:
        raise ValueError("metrics failed")

    transport.push_metrics_hook = fail_metrics
    with pytest.raises(ValueError, match="metrics failed"):
        await transport.handle_async_request(
            httpx.Request("GET", "https://example.com/")
        )

    assert semaphores.released.is_set()
    assert inner.body.closed.is_set()


async def test_response_close_error_does_not_replace_metrics_error(caplog):
    inner = _ResponseTransport(body=_FailingBody())
    semaphores = _SemaphoreManager()
    semaphores.release_allowed.set()
    transport = _transport(inner, semaphores)
    logger_name = "test_response_cleanup"
    transport.logger = logging.LoggerAdapter(logging.getLogger(logger_name), {})
    metrics_error = ValueError("metrics failed")

    async def fail_metrics(metrics: ConcurrencyRateLimiterMetrics) -> None:
        raise metrics_error

    transport.push_metrics_hook = fail_metrics
    with caplog.at_level(logging.ERROR, logger=logger_name):
        with pytest.raises(ValueError, match="metrics failed") as exc_info:
            await transport.handle_async_request(
                httpx.Request("GET", "https://example.com/")
            )

    assert exc_info.value is metrics_error
    assert semaphores.released.is_set()
    assert inner.body.close_started.is_set()
    records = [
        record
        for record in caplog.records
        if record.message == "Failed to close response after request failure"
    ]
    assert len(records) == 1
    assert records[0].exc_info is not None
    assert isinstance(records[0].exc_info[1], OSError)
    assert str(records[0].exc_info[1]) == "response close failed"


async def test_response_close_error_does_not_replace_cancellation():
    inner = _ResponseTransport(body=_FailingBody())
    semaphores = _SemaphoreManager()
    cancellations: list[asyncio.CancelledError] = []

    async def request() -> None:
        try:
            await _transport(inner, semaphores).handle_async_request(
                httpx.Request("GET", "https://example.com/")
            )
        except asyncio.CancelledError as exc:
            # Python 3.10 can lose the message when awaiting a cancelled task.
            cancellations.append(exc)
            raise

    task = asyncio.create_task(request())

    try:
        await asyncio.wait_for(semaphores.release_started.wait(), timeout=1)
        task.cancel("request cancelled")
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(cancellations) == 1
        assert str(cancellations[0]) == "request cancelled"
        assert inner.body.close_started.is_set()
    finally:
        semaphores.release_allowed.set()
        await asyncio.wait_for(semaphores.released.wait(), timeout=1)


async def test_response_close_error_does_not_replace_timeout():
    inner = _ResponseTransport(body=_FailingBody())
    semaphores = _SemaphoreManager()
    task = asyncio.create_task(
        _transport(inner, semaphores).handle_async_request(
            httpx.Request("GET", "https://example.com/")
        )
    )

    try:
        await asyncio.wait_for(semaphores.release_started.wait(), timeout=1)
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(task, timeout=0.01)
        assert inner.body.close_started.is_set()
    finally:
        semaphores.release_allowed.set()
        await asyncio.wait_for(semaphores.released.wait(), timeout=1)


async def test_semaphore_release_error_closes_response():
    inner = _ResponseTransport()
    inner.body.close_allowed.set()
    semaphores = _SemaphoreManager(fail_on_release=True)
    semaphores.release_allowed.set()

    with pytest.raises(RuntimeError, match="semaphore release failed"):
        await _transport(inner, semaphores).handle_async_request(
            httpx.Request("GET", "https://example.com/")
        )

    assert inner.body.closed.is_set()


async def test_response_close_error_does_not_replace_semaphore_release_error():
    inner = _ResponseTransport(body=_FailingBody())
    semaphores = _SemaphoreManager(fail_on_release=True)
    semaphores.release_allowed.set()

    with pytest.raises(RuntimeError, match="semaphore release failed"):
        await _transport(inner, semaphores).handle_async_request(
            httpx.Request("GET", "https://example.com/")
        )

    assert semaphores.released.is_set()
    assert inner.body.close_started.is_set()


async def test_second_cancellation_does_not_interrupt_response_close():
    inner = _ResponseTransport()
    semaphores = _SemaphoreManager()
    task = asyncio.create_task(
        _transport(inner, semaphores).handle_async_request(
            httpx.Request("GET", "https://example.com/")
        )
    )

    try:
        await asyncio.wait_for(semaphores.release_started.wait(), timeout=1)
        task.cancel()
        await asyncio.wait_for(inner.body.close_started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        inner.body.close_allowed.set()
        await asyncio.wait_for(inner.body.closed.wait(), timeout=1)
    finally:
        inner.body.close_allowed.set()
        semaphores.release_allowed.set()
        await asyncio.wait_for(semaphores.released.wait(), timeout=1)


async def test_cancelled_response_releases_connection_in_httpx_pool():
    connections: set[asyncio.Task[None]] = set()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
            await writer.drain()
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()

    def accept(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.create_task(serve(reader, writer))
        connections.add(task)
        task.add_done_callback(connections.discard)

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    semaphores = _SemaphoreManager()
    transport = ConcurrencyRateLimiterTransport(
        limits=[GlobalConcurrencyRateLimit(concurrency_limit=1)],
        semaphore_manager=semaphores,
        inner_transport=httpx.AsyncHTTPTransport(
            limits=httpx.Limits(max_connections=1)
        ),
        logger=None,
    )

    try:
        async with httpx.AsyncClient(transport=transport, timeout=1) as client:
            task = asyncio.create_task(client.get(f"http://127.0.0.1:{port}/"))
            try:
                await asyncio.wait_for(semaphores.release_started.wait(), timeout=1)
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            finally:
                semaphores.release_allowed.set()

            await asyncio.wait_for(semaphores.released.wait(), timeout=1)
            response = await client.get(f"http://127.0.0.1:{port}/")
            assert response.content == b"ok"
    finally:
        server.close()
        await server.wait_closed()
        await asyncio.gather(*connections)
