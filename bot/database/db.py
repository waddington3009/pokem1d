"""Engine assíncrona, sessões e helpers de acesso ao banco."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

from .models import Base, Guild, User


class Database:
    """Encapsula engine + sessionmaker."""

    def __init__(self, url: str):
        # echo=False; aumente para depurar SQL.
        self.engine = create_async_engine(url, echo=False, future=True)
        self.sessionmaker = async_sessionmaker(
            self.engine, expire_on_commit=False, class_=AsyncSession
        )

    async def create_all(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self.engine.dispose()

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.sessionmaker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise


# Instância global (preenchida em init_db)
_db: Database | None = None


def get_db() -> Database:
    if _db is None:
        raise RuntimeError("Banco não inicializado. Chame init_db() primeiro.")
    return _db


async def init_db(url: str | None = None) -> Database:
    global _db
    _db = Database(url or settings.database_url)
    await _db.create_all()
    return _db


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    async with get_db().session() as session:
        yield session


# ---------------------------------------------------------------------------
# Helpers get-or-create
# ---------------------------------------------------------------------------
async def get_or_create_user(session: AsyncSession, discord_id: int) -> User:
    user = await session.scalar(select(User).where(User.discord_id == discord_id))
    if user is None:
        user = User(discord_id=discord_id)
        session.add(user)
        await session.flush()  # garante user.id
    return user


async def get_or_create_guild(session: AsyncSession, guild_id: int) -> Guild:
    guild = await session.get(Guild, guild_id)
    if guild is None:
        guild = Guild(guild_id=guild_id)
        session.add(guild)
        await session.flush()
    return guild
