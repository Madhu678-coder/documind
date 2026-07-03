from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, future=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    """Create tables on startup. This is a small standalone tool — a full Alembic
    chain is overkill; `create_all` is enough and stays idempotent across restarts."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
