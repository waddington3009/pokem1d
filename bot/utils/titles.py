"""Atribuição do cargo de TÍTULO ao membro conforme o nível de treinador.

Tudo aqui é tolerante a falhas: se o bot não tiver permissão de 'Gerenciar
Cargos', ou o cargo estiver acima do bot na hierarquia, simplesmente não faz
nada (loga e segue) — nunca quebra o /menu.
"""
from __future__ import annotations

import logging

import discord

from bot.data.titles import TITLE_NAMES, TITLES, title_for_level

log = logging.getLogger(__name__)


async def ensure_title_role(guild: discord.Guild, name: str, color: int) -> discord.Role | None:
    """Encontra (ou cria) o cargo do título. None se não der p/ criar."""
    role = discord.utils.get(guild.roles, name=name)
    if role is not None:
        return role
    me = guild.me
    if me is None or not me.guild_permissions.manage_roles:
        return None
    try:
        return await guild.create_role(
            name=name, colour=discord.Colour(color), hoist=True, mentionable=False,
            reason="Título de treinador PokeM1D")
    except discord.HTTPException:
        log.warning("Falha ao criar cargo de título '%s' em %s", name, guild.id)
        return None


async def sync_member_title(member: discord.Member | None, trainer_level: int) -> str | None:
    """Garante que o membro tenha só o cargo de título do seu nível atual.

    Retorna o nome do título recém-concedido (para anunciar), ou None.
    """
    try:
        if member is None or getattr(member, "guild", None) is None:
            return None
        target = title_for_level(trainer_level)
        if target is None:
            return None
        _, target_name, target_color = target
        current = [r for r in member.roles if r.name in TITLE_NAMES]
        has_target = any(r.name == target_name for r in current)
        to_remove = [r for r in current if r.name != target_name]
        if has_target and not to_remove:
            return None  # já está certo — nenhuma chamada à API
        me = member.guild.me
        if me is None or not me.guild_permissions.manage_roles:
            return None
        granted: str | None = None
        if not has_target:
            role = await ensure_title_role(member.guild, target_name, target_color)
            if role is not None and role < me.top_role:
                await member.add_roles(role, reason="Título de treinador")
                granted = target_name
        removable = [r for r in to_remove if r < me.top_role]
        if removable:
            await member.remove_roles(*removable, reason="Atualização de título")
        return granted
    except Exception:  # noqa: BLE001 — nunca deixa quebrar o fluxo do menu
        log.exception("Falha ao sincronizar título")
        return None


async def setup_all_title_roles(guild: discord.Guild) -> tuple[int, int]:
    """Cria todos os cargos de título que ainda não existem. Retorna (criados, total)."""
    criados = 0
    for _, name, color in TITLES:
        if discord.utils.get(guild.roles, name=name) is None:
            role = await ensure_title_role(guild, name, color)
            if role is not None:
                criados += 1
    return criados, len(TITLES)
