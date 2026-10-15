import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable
from typing import Generic, TypeVar

from pydantic import BaseModel

from .config import get_settings

T = TypeVar("T")


def _weigh(value: object) -> int:
    if isinstance(value, BaseModel):
        return len(value.__pydantic_serializer__.to_json(value))
    if isinstance(value, (list, tuple)):
        return sum(_weigh(item) for item in value) + 64
    return 256


class TTLCache(Generic[T]):
    """Bounded in-process cache for read-mostly public responses.

    Capped by entry count and by an estimate of the serialized size, whichever
    is hit first, so a burst of distinct keys evicts old entries instead of
    growing the process. One loader runs per key at a time; concurrent misses
    wait for it rather than each going to the database.
    """

    def __init__(self, *, ttl_seconds: float, max_entries: int, max_bytes: int) -> None:
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self.bytes = 0
        self._entries: OrderedDict[Hashable, tuple[float, int, T]] = OrderedDict()
        self._inflight: dict[Hashable, asyncio.Future[T]] = {}

    def __len__(self) -> int:
        return len(self._entries)

    def get(self, key: Hashable) -> T | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at, _, value = entry
        if expires_at <= time.monotonic():
            self._drop(key)
            return None
        self._entries.move_to_end(key)
        return value

    def put(self, key: Hashable, value: T) -> None:
        size = _weigh(value)
        if size > self.max_bytes:
            return
        if key in self._entries:
            self._drop(key)
        self._entries[key] = (time.monotonic() + self.ttl, size, value)
        self.bytes += size
        while len(self._entries) > self.max_entries or self.bytes > self.max_bytes:
            self._drop(next(iter(self._entries)))

    def clear(self) -> None:
        self._entries.clear()
        self.bytes = 0

    def _drop(self, key: Hashable) -> None:
        _, size, _ = self._entries.pop(key)
        self.bytes -= size

    async def get_or_load(self, key: Hashable, load: Callable[[], Awaitable[T]]) -> T:
        if self.ttl <= 0:
            return await load()
        hit = self.get(key)
        if hit is not None:
            return hit
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future[T] = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await load()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except Exception as exc:
            future.set_exception(exc)
            # Retrieved here so a miss nobody else was waiting on does not log
            # "exception was never retrieved".
            future.exception()
            raise
        else:
            self.put(key, value)
            future.set_result(value)
            return value
        finally:
            self._inflight.pop(key, None)


_public: TTLCache | None = None


def public_cache() -> TTLCache:
    global _public
    if _public is None:
        settings = get_settings()
        # Cached pages carry signed avatar URLs, which must not outlive their
        # signature while still being served.
        _public = TTLCache(
            ttl_seconds=min(
                settings.public_cache_ttl_seconds, settings.signed_url_ttl_seconds / 2
            ),
            max_entries=settings.public_cache_max_entries,
            max_bytes=settings.public_cache_max_bytes,
        )
    return _public


def reset_public_cache() -> None:
    global _public
    _public = None
