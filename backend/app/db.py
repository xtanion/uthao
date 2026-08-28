from collections.abc import AsyncIterator
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


# libpq query parameters that asyncpg either spells differently or does not
# take on the connection string at all.
_LIBPQ_ONLY = {"sslmode", "channel_binding", "target_session_attrs"}

# Supabase's Supavisor and PgBouncer in transaction mode hand each query a
# different backend connection, so a prepared statement made on one is missing
# on the next. asyncpg prepares everything by default, which turns into
# "prepared statement _asyncpg_stmt_1 does not exist" under load rather than
# immediately - the worst way to find out.
POOLER_PORT = 6543
_POOLER_HOSTS = ("pooler.", "pgbouncer")


def through_a_pooler(netloc: str) -> bool:
    host = netloc.rsplit("@", 1)[-1].lower()
    if host.rsplit(":", 1)[-1] == str(POOLER_PORT):
        return True
    return any(marker in host for marker in _POOLER_HOSTS)


def normalized(url: str) -> tuple[str, dict]:
    """Turn a connection string a managed Postgres handed out into one asyncpg
    accepts.

    Every provider gives you `postgresql://.../db?sslmode=require`. The driver
    is asyncpg, which speaks `ssl=` rather than `sslmode=` and would otherwise
    fail with an unexpected-keyword error on the first connection - a confusing
    way to discover this on a deploy.
    """
    if url.startswith("sqlite"):
        return url, {"check_same_thread": False}

    # A connection string copied from a dashboard still says [YOUR-PASSWORD].
    # Left alone, urlsplit reads the brackets as an IPv6 literal and complains
    # about the *hostname*, which sends you looking in the wrong place.
    head, _, _ = url.rpartition("@")
    if "[" in head and "]" in head:
        raise ValueError(
            "DATABASE_URL still has the placeholder password from the provider's "
            "dashboard. Replace the [...] part with the real one."
        )

    scheme, netloc, path, query, fragment = urlsplit(url)
    if scheme in {"postgres", "postgresql"}:
        scheme = "postgresql+asyncpg"
    if not scheme.startswith("postgresql"):
        return url, {}

    kept = []
    connect: dict = {}
    for key, value in parse_qsl(query, keep_blank_values=True):
        if key == "sslmode":
            # asyncpg takes the same words under a different name.
            connect["ssl"] = value
        elif key not in _LIBPQ_ONLY:
            kept.append((key, value))

    if through_a_pooler(netloc):
        # Two caches, and both have to go: asyncpg's own, and the one
        # SQLAlchemy's dialect keeps on top of it.
        connect["statement_cache_size"] = 0
        if not any(key == "prepared_statement_cache_size" for key, _ in kept):
            kept.append(("prepared_statement_cache_size", "0"))

    return urlunsplit((scheme, netloc, path, urlencode(kept), fragment)), connect


def engine() -> AsyncEngine:
    global _engine, _sessionmaker
    if _engine is None:
        url, connect_args = normalized(get_settings().database_url)
        kwargs: dict = {"future": True, "connect_args": connect_args}
        if not url.startswith("sqlite"):
            # Managed Postgres and the proxies in front of it drop idle
            # connections; without this the first query after one goes away
            # fails rather than reconnecting.
            kwargs["pool_pre_ping"] = True
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 5
            kwargs["pool_recycle"] = 1800
        _engine = create_async_engine(url, **kwargs)
        _sessionmaker = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def sessionmaker() -> async_sessionmaker[AsyncSession]:
    engine()
    assert _sessionmaker is not None
    return _sessionmaker


async def dispose() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessionmaker()() as session:
        yield session
