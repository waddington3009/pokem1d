"""Boas-vindas: ao entrar no servidor, o membro ganha o cargo 🥚 Novato de Pallet
e é recebido no canal de lobby (setlobby) com um cartão de imagem + avatar.
"""
from __future__ import annotations

import logging

import discord
from discord.ext import commands
from sqlalchemy import select

from config import settings
from bot.database.db import get_or_create_guild, session_scope
from bot.database.models import User
from bot.utils.titles import sync_member_title
from bot.utils.welcome_scene import render_welcome

log = logging.getLogger(__name__)


class Welcome(commands.Cog, name="BoasVindas"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        if member.bot:
            return

        # 1) cargo de título conforme o nível (Novato p/ quem é novo; o título certo
        #    p/ quem já jogou em outro servidor — os dados são globais).
        try:
            async with session_scope() as session:
                user = await session.scalar(select(User).where(User.discord_id == member.id))
                level = user.trainer_level if user else 1
            await sync_member_title(member, level)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao dar cargo de boas-vindas a %s", member.id)

        # 2) cartão de boas-vindas no canal de lobby (se configurado)
        try:
            async with session_scope() as session:
                guild = await get_or_create_guild(session, member.guild.id)
                lobby_id = guild.lobby_channel_id
            if not lobby_id:
                return
            channel = member.guild.get_channel(lobby_id)
            if channel is None:
                return
            try:
                avatar_bytes = await member.display_avatar.with_size(256).read()
            except Exception:  # noqa: BLE001
                avatar_bytes = None
            buf = await render_welcome(avatar_bytes, member.display_name, member.guild.member_count)
            emb = discord.Embed(
                title=f"🎉 Bem-vindo(a), {member.display_name}!",
                description=(f"{member.mention} acabou de chegar em **{member.guild.name}**! 🌿\n\n"
                            f"Você já é um **🥚 Novato de Pallet** — abra o **`/menu`** para "
                            f"escolher seu inicial e começar a aventura!"),
                color=settings.color_success)
            file = None
            if buf is not None:
                file = discord.File(buf, filename="welcome.png")
                emb.set_image(url="attachment://welcome.png")
            await channel.send(content=member.mention, embed=emb,
                               **({"file": file} if file else {}))
        except discord.Forbidden:
            log.warning("Sem permissão p/ enviar boas-vindas em %s", member.guild.id)
        except Exception:  # noqa: BLE001
            log.exception("Falha ao enviar boas-vindas em %s", member.guild.id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
