"""Engine assíncrona, sessões e helpers de acesso ao banco."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from config import settings

from .models import Base, Guild, User


def _auto_migrate(conn) -> None:
    """Adiciona colunas que existem nos modelos mas não na tabela do banco.

    Roda sobre uma conexão síncrona (via run_sync). Idempotente: só adiciona
    o que falta, como coluna anulável (seguro p/ tabelas com dados). Funciona
    em PostgreSQL e SQLite.
    """
    inspector = inspect(conn)
    existing_tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue  # create_all já criou a tabela completa
        db_columns = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in db_columns:
                continue
            col_type = column.type.compile(dialect=conn.dialect)
            conn.execute(text(
                f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
            ))


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
            await conn.run_sync(_auto_migrate)

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
