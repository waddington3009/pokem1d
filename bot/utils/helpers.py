"""Funções de acesso a dados compartilhadas entre os cogs."""
from __future__ import annotations

import random

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.data.natures import random_nature
from bot.data.pokemon_data import Species
from bot.database.db import get_or_create_user
from bot.database.models import InventoryItem, PokedexEntry, Pokemon, User
from bot.utils.stats import apply_xp, generate_ivs


async def fetch_user(session: AsyncSession, discord_id: int) -> User:
    return await get_or_create_user(session, discord_id)


async def pokemon_count(session: AsyncSession, user_id: int) -> int:
    return await session.scalar(
        select(func.count(Pokemon.id)).where(Pokemon.owner_id == user_id)
    ) or 0


async def get_pokemon_by_idx(
    session: AsyncSession, user_id: int, idx: int
) -> Pokemon | None:
    return await session.scalar(
        select(Pokemon).where(Pokemon.owner_id == user_id, Pokemon.idx == idx)
    )


async def get_selected(session: AsyncSession, user: User) -> Pokemon | None:
    if user.selected_id is None:
        return None
    return await session.get(Pokemon, user.selected_id)


async def list_pokemon(
    session: AsyncSession, user_id: int, order_by=Pokemon.idx
) -> list[Pokemon]:
    res = await session.scalars(
        select(Pokemon).where(Pokemon.owner_id == user_id).order_by(order_by)
    )
    return list(res)


async def create_pokemon(
    session: AsyncSession,
    user: User,
    species: Species,
    *,
    level: int | None = None,
    shiny: bool = False,
    iv_rolls: int = 1,
    iv_floor: int = 0,
    select_if_first: bool = True,
) -> Pokemon:
    """Cria e persiste um novo pokémon para o usuário."""
    ivs = generate_ivs(rolls=iv_rolls, floor=iv_floor)
    if level is None:
        level = random.randint(1, 30)
    idx = user.next_idx
    user.next_idx += 1

    poke = Pokemon(
        owner_id=user.id,
        original_owner_id=user.discord_id,
        species_id=species.id,
        idx=idx,
        level=level,
        xp=0,
        nature=random_nature(),
        shiny=shiny,
        iv_hp=ivs["iv_hp"], iv_atk=ivs["iv_atk"], iv_def=ivs["iv_def"],
        iv_spa=ivs["iv_spa"], iv_spd=ivs["iv_spd"], iv_spe=ivs["iv_spe"],
    )
    session.add(poke)
    await session.flush()

    if select_if_first and user.selected_id is None:
        user.selected_id = poke.id
    return poke


async def update_pokedex(
    session: AsyncSession, user_id: int, species_id: int,
    seen: int = 0, caught: int = 0,
) -> bool:
    """Atualiza o registro da Pokédex. Retorna True se for captura inédita."""
    entry = await session.scalar(
        select(PokedexEntry).where(
            PokedexEntry.user_id == user_id, PokedexEntry.species_id == species_id
        )
    )
    new_catch = False
    if entry is None:
        entry = PokedexEntry(user_id=user_id, species_id=species_id, seen=seen, caught=caught)
        session.add(entry)
        new_catch = caught > 0
    else:
        if caught > 0 and entry.caught == 0:
            new_catch = True
        entry.seen += seen
        entry.caught += caught
    return new_catch


async def get_inventory(session: AsyncSession, user_id: int) -> dict[str, int]:
    res = await session.scalars(
        select(InventoryItem).where(InventoryItem.user_id == user_id)
    )
    return {it.item_key: it.quantity for it in res if it.quantity > 0}


async def add_item(
    session: AsyncSession, user_id: int, item_key: str, qty: int = 1
) -> int:
    """Adiciona (ou remove, se qty<0) itens. Retorna a nova quantidade."""
    item = await session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_id == user_id, InventoryItem.item_key == item_key
        )
    )
    if item is None:
        item = InventoryItem(user_id=user_id, item_key=item_key, quantity=0)
        session.add(item)
    item.quantity = max(0, item.quantity + qty)
    return item.quantity


async def take_item(session: AsyncSession, user_id: int, item_key: str, qty: int = 1) -> bool:
    """Consome itens se houver quantidade suficiente. Retorna sucesso."""
    item = await session.scalar(
        select(InventoryItem).where(
            InventoryItem.user_id == user_id, InventoryItem.item_key == item_key
        )
    )
    if item is None or item.quantity < qty:
        return False
    item.quantity -= qty
    return True


def grant_trainer_xp(user: User, amount: int) -> int:
    """Concede XP de treinador e processa level-ups. Retorna níveis ganhos."""
    user.trainer_xp += amount
    leveled = 0
    while user.trainer_xp >= user.xp_to_next:
        user.trainer_xp -= user.xp_to_next
        user.trainer_level += 1
        leveled += 1
    return leveled
