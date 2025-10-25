import asyncio
import contextlib
from dataclasses import dataclass, field
from types import TracebackType
from typing import Optional, Type


@dataclass
class SafeAsyncExitStack:
    """
    A wrapper around asyncio.AsyncExitStack that ensures its
    unwinding process (__aexit__) is protected against cancellation.
    """

    _stack: contextlib.AsyncExitStack = field(default_factory=contextlib.AsyncExitStack)

    async def __aenter__(self):
        await self._stack.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> Optional[bool]:
        # We protected the __aexit__ process against cancellation
        return await asyncio.shield(self._stack.__aexit__(exc_type, exc, tb))

    async def enter_async_context(self, cm):
        return await self._stack.enter_async_context(cm)
