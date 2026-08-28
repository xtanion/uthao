import asyncio

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import normalized
from app.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> tuple[str, dict]:
    """The same normalisation the app uses. Reading the raw setting here would
    hand `postgresql://` to the default psycopg2 driver, which is not what is
    installed, and the migration would fail on a driver import rather than on
    anything to do with the schema."""
    from app.config import get_settings

    return normalized(get_settings().database_url)


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # SQLite cannot ALTER most things in place; batch mode rebuilds the
        # table instead, so the same migration runs on both backends.
        render_as_batch=connection.dialect.name == "sqlite",
    )


def run_offline() -> None:
    url, _ = _url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    url, connect_args = _url()
    engine = create_async_engine(
        url, connect_args=connect_args, poolclass=pool.NullPool
    )
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    # A caller that already holds a connection passes it in; the test suite
    # does this to migrate the database it just created.
    existing = config.attributes.get("connection")
    if existing is not None:
        _run(existing)
    else:
        asyncio.run(run_online())
