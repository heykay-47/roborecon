from collections.abc import AsyncGenerator
from time import perf_counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.common.timing import current_read_timing
from app.config import settings

engine_options = {}
if settings.serverless:
    # Neon pooled endpoints use PgBouncer transaction pooling; asyncpg's
    # prepared-statement cache must be disabled for that connection mode.
    engine_options = {
        "poolclass": NullPool,
        "connect_args": {"statement_cache_size": 0},
    }

engine = create_async_engine(settings.database_url, **engine_options)


class TimedAsyncSession(AsyncSession):
    async def execute(self, *args: Any, **kwargs: Any):
        started = perf_counter()
        try:
            return await super().execute(*args, **kwargs)
        finally:
            timing = current_read_timing.get()
            if timing is not None:
                timing.add_database_ms((perf_counter() - started) * 1000)

    async def get(self, *args: Any, **kwargs: Any):
        started = perf_counter()
        try:
            return await super().get(*args, **kwargs)
        finally:
            timing = current_read_timing.get()
            if timing is not None:
                timing.add_database_ms((perf_counter() - started) * 1000)


async_session = async_sessionmaker(
    engine,
    class_=TimedAsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yield a database session for FastAPI dependency injection."""
    async with async_session() as session:
        yield session
