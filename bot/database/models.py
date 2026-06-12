"""Modelos do banco de dados (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Guild(Base):
    """Configuração por servidor."""

    __tablename__ = "guilds"

    guild_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    prefix: Mapped[str | None] = mapped_column(String(8), default=None)
    language: Mapped[str] = mapped_column(String(4), default="pt")
    spawn_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    redirect_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    # canal único legado (mantido p/ compatibilidade; migrado para game_channels)
    game_channel_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    # se NÃO vazio, comandos e spawns só funcionam nestes canais
    game_channels: Mapped[list] = mapped_column(JSON, default=list)
    spawns_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # lista de IDs de canais bloqueados para spawn
    blacklist: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    """Treinador (jogador)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    discord_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)

    coins: Mapped[int] = mapped_column(Integer, default=0)
    trainer_xp: Mapped[int] = mapped_column(Integer, default=0)
    trainer_level: Mapped[int] = mapped_column(Integer, default=1)

    selected_id: Mapped[int | None] = mapped_column(
        ForeignKey("pokemon.id", ondelete="SET NULL"), default=None
    )
    next_idx: Mapped[int] = mapped_column(Integer, default=1)  # próximo índice por usuário
    # time de batalha: lista de índices (idx) de pokémon, até 3
    party: Mapped[list] = mapped_column(JSON, default=list)

    # Daily / streak
    daily_streak: Mapped[int] = mapped_column(Integer, default=0)
    last_daily: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    # Estatísticas acumuladas
    total_caught: Mapped[int] = mapped_column(Integer, default=0)
    total_shiny: Mapped[int] = mapped_column(Integer, default=0)
    battles_won: Mapped[int] = mapped_column(Integer, default=0)
    battles_total: Mapped[int] = mapped_column(Integer, default=0)

    # Missões / conquistas (estado em JSON)
    quest_progress: Mapped[dict] = mapped_column(JSON, default=dict)
    last_quest_reset: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), default=None
    )
    achievements: Mapped[list] = mapped_column(JSON, default=list)

    # Liga / Ginásios
    badges: Mapped[list] = mapped_column(JSON, default=list)        # chaves dos desafios vencidos
    badge_count: Mapped[int] = mapped_column(Integer, default=0)    # p/ ranking
    gym_cooldowns: Mapped[dict] = mapped_column(JSON, default=dict)  # revanche: key -> epoch

    language: Mapped[str | None] = mapped_column(String(4), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    pokemons: Mapped[list["Pokemon"]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        foreign_keys="Pokemon.owner_id",
    )

    @property
    def xp_to_next(self) -> int:
        """XP necessário para o próximo nível de treinador."""
        return 100 + (self.trainer_level - 1) * 75


class Pokemon(Base):
    """Um pokémon possuído por um usuário."""

    __tablename__ = "pokemon"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    original_owner_id: Mapped[int | None] = mapped_column(BigInteger, default=None)

    species_id: Mapped[int] = mapped_column(Integer, index=True)
    idx: Mapped[int] = mapped_column(Integer, default=0)  # índice exibido ao usuário

    level: Mapped[int] = mapped_column(Integer, default=1)
    xp: Mapped[int] = mapped_column(Integer, default=0)

    iv_hp: Mapped[int] = mapped_column(Integer, default=0)
    iv_atk: Mapped[int] = mapped_column(Integer, default=0)
    iv_def: Mapped[int] = mapped_column(Integer, default=0)
    iv_spa: Mapped[int] = mapped_column(Integer, default=0)
    iv_spd: Mapped[int] = mapped_column(Integer, default=0)
    iv_spe: Mapped[int] = mapped_column(Integer, default=0)

    nature: Mapped[str] = mapped_column(String(16), default="Hardy")
    shiny: Mapped[bool] = mapped_column(Boolean, default=False)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    nickname: Mapped[str | None] = mapped_column(String(32), default=None)
    held_item: Mapped[str | None] = mapped_column(String(32), default=None)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped["User"] = relationship(back_populates="pokemons", foreign_keys=[owner_id])

    # ---- Helpers de IV ----
    @property
    def iv_total(self) -> int:
        return (
            self.iv_hp + self.iv_atk + self.iv_def
            + self.iv_spa + self.iv_spd + self.iv_spe
        )

    @property
    def iv_percent(self) -> float:
        return self.iv_total / (31 * 6) * 100

    @property
    def xp_to_next(self) -> int:
        """XP necessário para subir do nível atual (curva medium-fast simplificada)."""
        return self.level * 25 + 50


class PokedexEntry(Base):
    """Registro de quais espécies o usuário já viu/capturou."""

    __tablename__ = "pokedex_entries"
    __table_args__ = (UniqueConstraint("user_id", "species_id", name="uq_pokedex"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    species_id: Mapped[int] = mapped_column(Integer, index=True)
    seen: Mapped[int] = mapped_column(Integer, default=0)
    caught: Mapped[int] = mapped_column(Integer, default=0)


class InventoryItem(Base):
    """Itens no inventário do usuário."""

    __tablename__ = "inventory"
    __table_args__ = (UniqueConstraint("user_id", "item_key", name="uq_inventory"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    item_key: Mapped[str] = mapped_column(String(32), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)


class MarketListing(Base):
    """Anúncio de venda de pokémon entre jogadores."""

    __tablename__ = "market"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    seller_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    pokemon_id: Mapped[int] = mapped_column(
        ForeignKey("pokemon.id", ondelete="CASCADE"), unique=True
    )
    price: Mapped[int] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
