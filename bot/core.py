"""Subclasse do bot: prefixo dinâmico, carga de dados e extensões."""
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from config import settings
from bot.data.pokemon_data import POKEDEX
from bot.database.db import get_or_create_guild, init_db, session_scope

log = logging.getLogger("pokebot")

# Comandos utilitários liberados em qualquer canal (mesmo com trava de canal ativa)
ALWAYS_ALLOWED = {"help", "ping", "botinfo"}


class WrongChannel(commands.CheckFailure):
    """Comando usado fora dos canais de jogo definidos."""

    def __init__(self, channel_ids: list[int]) -> None:
        self.channel_ids = channel_ids
        super().__init__("Comando usado no canal errado.")


EXTENSIONS = [
    "bot.cogs.admin",
    "bot.cogs.spawning",
    "bot.cogs.catching",
    "bot.cogs.explore",
    "bot.cogs.pokedex",
    "bot.cogs.evolution",
    "bot.cogs.economy",
    "bot.cogs.items",
    "bot.cogs.trading",
    "bot.cogs.battle",
    "bot.cogs.progression",
    "bot.cogs.general",
    "bot.cogs.gyms",
    "bot.cogs.owner",
]


async def _prefix_callable(bot: "PokeBot", message: discord.Message):
    default = settings.default_prefix
    if message.guild is None:
        return commands.when_mentioned_or(default)(bot, message)
    prefix = bot.prefix_cache.get(message.guild.id)
    if prefix is None:
        async with session_scope() as session:
            guild = await get_or_create_guild(session, message.guild.id)
            prefix = guild.prefix or default
        bot.prefix_cache[message.guild.id] = prefix
    return commands.when_mentioned_or(prefix)(bot, message)


class PokeBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # necessário p/ ler comandos por prefixo
        intents.members = True
        super().__init__(
            command_prefix=_prefix_callable,
            intents=intents,
            case_insensitive=True,
            owner_ids=set(settings.owner_ids) or None,
            help_command=commands.DefaultHelpCommand(no_category="Geral"),
            activity=discord.Game(name=f"{settings.default_prefix}help • Gotta catch 'em all!"),
        )
        # cache de prefixos por servidor (evita hit no DB a cada mensagem)
        self.prefix_cache: dict[int, str] = {}
        # cache dos canais de jogo por servidor (lista vazia = liberado em qualquer canal)
        self.game_channels_cache: dict[int, list[int]] = {}
        # verificação global: trava comandos fora dos canais de jogo
        self.add_check(self._channel_lock_check)

    async def setup_hook(self) -> None:
        POKEDEX.load()
        log.info("Pokédex carregada: %d espécies", POKEDEX.count())
        await init_db()
        log.info("Banco de dados inicializado.")
        for ext in EXTENSIONS:
            try:
                await self.load_extension(ext)
                log.info("Extensão carregada: %s", ext)
            except Exception:
                log.exception("Falha ao carregar extensão %s", ext)

    async def on_ready(self) -> None:
        log.info("Conectado como %s (ID %s)", self.user, self.user.id if self.user else "?")
        log.info("Servidores: %d", len(self.guilds))

    def update_prefix_cache(self, guild_id: int, prefix: str) -> None:
        self.prefix_cache[guild_id] = prefix

    # ---- Trava de canais de jogo ----
    @staticmethod
    def _merge_channels(guild) -> list[int]:
        """Lista de canais de jogo (mescla o campo novo com o legado)."""
        channels = list(guild.game_channels or [])
        if not channels and guild.game_channel_id:
            channels = [guild.game_channel_id]
        return channels

    async def get_game_channels(self, guild_id: int) -> list[int]:
        if guild_id not in self.game_channels_cache:
            async with session_scope() as session:
                guild = await get_or_create_guild(session, guild_id)
                self.game_channels_cache[guild_id] = self._merge_channels(guild)
        return self.game_channels_cache[guild_id]

    def set_game_channels_cache(self, guild_id: int, channels: list[int]) -> None:
        self.game_channels_cache[guild_id] = list(channels)

    async def _channel_lock_check(self, ctx: commands.Context) -> bool:
        # DMs e comandos de admin/utilitários passam em qualquer lugar
        if ctx.guild is None:
            return True
        if await self.is_owner(ctx.author):
            return True
        if ctx.cog and ctx.cog.qualified_name in ("Administração", "Dono"):
            return True
        if ctx.command and ctx.command.qualified_name in ALWAYS_ALLOWED:
            return True
        channels = await self.get_game_channels(ctx.guild.id)
        if not channels or ctx.channel.id in channels:
            return True
        raise WrongChannel(channels)

    async def on_command_error(self, ctx: commands.Context, error: Exception) -> None:
        # Trata os erros mais comuns de forma amigável; loga o resto.
        # Se o comando/cog tem handler próprio, não duplica a resposta.
        if ctx.command and ctx.command.has_error_handler():
            return
        if ctx.cog and ctx.cog.has_error_handler():
            return
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, WrongChannel):
            canais = ", ".join(f"<#{c}>" for c in error.channel_ids)
            await ctx.send(
                f"🚫 Os comandos do bot só funcionam em: {canais}.",
                delete_after=8,
            )
            return
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"⚠️ Faltou um argumento: `{error.param.name}`. "
                           f"Veja `{ctx.prefix}help {ctx.command}`.")
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(f"⚠️ Argumento inválido. Veja `{ctx.prefix}help {ctx.command}`.")
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("🚫 Você não tem permissão para usar esse comando.")
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send("🚫 Esse comando só funciona em servidores.")
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"⏳ Calma! Tente novamente em {error.retry_after:.1f}s.")
            return
        if isinstance(error, commands.CheckFailure):
            await ctx.send("🚫 Você não pode usar esse comando aqui.")
            return
        log.exception("Erro não tratado no comando %s", ctx.command, exc_info=error)
        await ctx.send("💥 Ocorreu um erro inesperado. Os logs foram registrados.")
