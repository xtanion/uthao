import asyncio

import pytest
from pydantic import BaseModel

from app.cache import TTLCache
from tests.conftest import sign_in
from tests.test_stats import REPORTER, file


class Blob(BaseModel):
    text: str


async def test_a_hit_does_not_load_again():
    cache = TTLCache(ttl_seconds=60, max_entries=8, max_bytes=10_000)
    calls = []

    async def load():
        calls.append(1)
        return Blob(text="x")

    assert (await cache.get_or_load("k", load)).text == "x"
    assert (await cache.get_or_load("k", load)).text == "x"
    assert len(calls) == 1


async def test_entries_expire():
    cache = TTLCache(ttl_seconds=0.01, max_entries=8, max_bytes=10_000)
    cache.put("k", Blob(text="x"))
    await asyncio.sleep(0.02)
    assert cache.get("k") is None
    assert cache.bytes == 0


def test_the_entry_cap_evicts_the_least_recently_used():
    cache = TTLCache(ttl_seconds=60, max_entries=2, max_bytes=10_000)
    cache.put("a", Blob(text="a"))
    cache.put("b", Blob(text="b"))
    cache.get("a")
    cache.put("c", Blob(text="c"))
    assert cache.get("b") is None
    assert cache.get("a") is not None
    assert cache.get("c") is not None


def test_the_byte_cap_evicts_until_it_fits():
    cache = TTLCache(ttl_seconds=60, max_entries=100, max_bytes=100)
    for key in range(5):
        cache.put(key, Blob(text="x" * 30))
    assert cache.bytes <= 100
    assert len(cache) == 2
    assert cache.get(4) is not None


def test_a_value_bigger_than_the_whole_budget_is_not_kept():
    cache = TTLCache(ttl_seconds=60, max_entries=100, max_bytes=50)
    cache.put("big", Blob(text="x" * 100))
    assert cache.get("big") is None
    assert cache.bytes == 0


async def test_concurrent_misses_share_one_load():
    cache = TTLCache(ttl_seconds=60, max_entries=8, max_bytes=10_000)
    calls = []

    async def load():
        calls.append(1)
        await asyncio.sleep(0.01)
        return Blob(text="x")

    results = await asyncio.gather(*(cache.get_or_load("k", load) for _ in range(5)))
    assert len(calls) == 1
    assert all(r.text == "x" for r in results)


async def test_a_failed_load_is_not_cached():
    cache = TTLCache(ttl_seconds=60, max_entries=8, max_bytes=10_000)

    async def fail():
        raise RuntimeError("down")

    with pytest.raises(RuntimeError):
        await cache.get_or_load("k", fail)

    async def load():
        return Blob(text="ok")

    assert (await cache.get_or_load("k", load)).text == "ok"


@pytest.fixture
def cached(monkeypatch):
    from app import cache
    from app.config import get_settings

    monkeypatch.setenv("PUBLIC_CACHE_TTL_SECONDS", "60")
    get_settings.cache_clear()
    cache.reset_public_cache()
    yield
    get_settings.cache_clear()
    cache.reset_public_cache()


async def test_stats_are_served_from_memory_within_the_ttl(client, sender, cached):
    token = await sign_in(client, sender, REPORTER)
    await file(client, token, "First")
    first = (await client.get("/stats", params={"lat": 19.0596, "lng": 72.8295})).json()
    await file(client, token, "Second")
    second = (await client.get("/stats", params={"lat": 19.0596, "lng": 72.8295})).json()
    assert first["totals"]["reported"] == 1
    assert second["totals"]["reported"] == 1
