"""Trava de conversa nos canais de JOGO (definidos via setchannel).

Nesses canais o foco é jogar pelo /menu (privado), então mensagens normais de
jogadores são apagadas com um aviso curto que some sozinho. Comandos por prefixo
(ex.: p!capturar) e mensagens de staff (Gerenciar Mensagens) passam normalmente.
"""
from __future__ import annotations

import time

import discord
from discord.ext import commands

from config import settings


class GameLock(commands.Cog, name="TravaDeCanal"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # (channel_id, user_id) -> último aviso (epoch) p/ não spammar o aviso
        self._warned: dict[tuple[int, int], float] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        # staff conversa à vontade
        perms = getattr(message.author, "guild_permissions", None)
        if perms is not None and (perms.manage_messages or perms.administrator):
            return
        # só nos canais de jogo definidos com setchannel
        channels = await self.bot.get_game_channels(message.guild.id)
        if not channels or message.channel.id not in channels:
            return
        # deixa comandos por prefixo rodarem (não apaga p!capturar etc.)
        prefix = self.bot.prefix_cache.get(message.guild.id, settings.default_prefix)
        content = message.content or ""
        bot_id = self.bot.user.id if self.bot.user else 0
        if content.startswith(prefix) or content.startswith((f"<@{bot_id}>", f"<@!{bot_id}>")):
            return
        # apaga a mensagem do jogador
        try:
            await message.delete()
        except discord.HTTPException:
            return  # sem permissão p/ apagar — não insiste
        # aviso curto (no máx. 1 a cada 15s por jogador/canal)
        key = (message.channel.id, message.author.id)
        now = time.time()
        if now - self._warned.get(key, 0) < 15:
            return
        self._warned[key] = now
        try:
            await message.channel.send(
                f"🔇 {message.author.mention}, este canal é **reservado para jogar**! "
                f"Use **`/menu`** para jogar (é privado, só você vê). 🎮",
                delete_after=8,
            )
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GameLock(bot))
