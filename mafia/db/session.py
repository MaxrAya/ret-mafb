from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from mafia.db.models import Base

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init_db(path: str) -> async_sessionmaker[AsyncSession]:
    global _engine, _session_factory
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    _engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _session_factory


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise RuntimeError("DB not initialised")
    return _session_factory


async def create_schema() -> None:
    if _engine is None:
        raise RuntimeError("DB not initialised")
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)


def _ensure_columns(sync_conn: Any) -> None:
    """Lightweight migration: add columns created after the first release."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    if "matches" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("matches")}
    if "progress_json" not in cols:
        sync_conn.execute(
            text("ALTER TABLE matches ADD COLUMN progress_json TEXT NOT NULL DEFAULT '{}'")
        )


async def dispose_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    factory = get_session_factory()
    async with factory() as session:
        yield session
        await session.commit()
