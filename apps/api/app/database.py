from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings

engine_options = {}
if settings.serverless:
    engine_options = {
        "poolclass": NullPool,
        "connect_args": {"statement_cache_size": 0},
    }

engine = create_async_engine(settings.database_url, **engine_options)

async_session = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Yield a database session for FastAPI dependency injection."""
    async with async_session() as session:
        yield session
