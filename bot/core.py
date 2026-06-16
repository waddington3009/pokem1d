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
ALWAYS_ALLOWED = {"help", "tutorial", "ping", "botinfo", "menu", "sync", "start"}

# Comandos que jogadores comuns AINDA podem usar por prefixo (o resto é só /menu).
# Mantemos o que é PÚBLICO por natureza: captura de spawn, PvP, ginásio e troca.
# (o duelo PvE saiu daqui de propósito — agora é privado pelo /menu → Duelar)
PREFIX_KEEP_FOR_USERS = {"capturar", "gym", "battle", "trade"}


class WrongChannel(commands.CheckFailure):
    """Comando usado fora dos canais de jogo definidos."""

    def __init__(self, channel_ids: list[int]) -> None:
        self.channel_ids = channel_ids
        super().__init__("Comando usado no canal errado.")


class PrefixDisabled(commands.CheckFailure):
    """Jogador comum tentou usar comando por prefixo (agora só via /menu)."""


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
    "bot.cogs.help_tutorial",
    "bot.cogs.hub",
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
            help_command=None,  # help próprio (cog help_tutorial)
            activity=discord.Game(name=f"{settings.default_prefix}help • Gotta catch 'em all!"),
        )
        # cache de prefixos por servidor (evita hit no DB a cada mensagem)
        self.prefix_cache: dict[int, str] = {}
        # cache dos canais de jogo por servidor (lista vazia = liberado em qualquer canal)
        self.game_channels_cache: dict[int, list[int]] = {}
        # garante o sync dos comandos de barra (/) só uma vez por processo
        self._slash_synced = False
        # bloqueia comandos por PREFIXO para jogadores comuns (eles usam /menu, privado)
        self.add_check(self._prefix_block_check)
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
        # publica os comandos de barra (/) em cada servidor — instantâneo (1x por processo)
        if not self._slash_synced:
            self._slash_synced = True
            for guild in self.guilds:
                try:
                    self.tree.copy_global_to(guild=guild)
                    cmds = await self.tree.sync(guild=guild)
                    log.info("Slash sync em %s: %d comando(s)", guild.id, len(cmds))
                except discord.Forbidden:
                    log.warning("Sem escopo 'applications.commands' em %s — reconvide o bot "
                                "com esse escopo para o /menu aparecer.", guild.id)
                except Exception:
                    log.exception("Falha no slash sync em %s", guild.id)

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

    # ---- Anúncio de capturas raras (canal de warning) ----
    async def announce_rare(self, guild, member, species, shiny: bool, level: int | None = None) -> None:
        """Anuncia, no canal configurado, quando alguém pega um Super-Raro+ ou shiny."""
        if guild is None or species is None:
            return
        if species.rarity not in ("superrare", "legendary", "mythical") and not shiny:
            return
        try:
            async with session_scope() as session:
                g = await get_or_create_guild(session, guild.id)
                ch_id = g.warning_channel_id
            if not ch_id:
                return
            channel = guild.get_channel(ch_id)
            if channel is None:
                return
            from bot.utils.rarity import RARITY_COLOR, RARITY_EMOJI, rarity_label
            emoji = RARITY_EMOJI.get(species.rarity, "")
            tier = rarity_label(species.rarity)
            title = "✨ SHINY encontrado!" if shiny else f"{emoji} {tier} capturado!"
            color = settings.color_shiny if shiny else RARITY_COLOR.get(species.rarity, settings.color_default)
            desc = (f"🎉 {member.mention} acabou de conseguir "
                    f"{'um ✨ **SHINY** ' if shiny else 'um '}**{species.name}**"
                    f"{f' (Nv {level})' if level else ''}!\n"
                    f"{emoji} Raridade: **{tier}**")
            emb = discord.Embed(title=title, description=desc, color=color)
            emb.set_thumbnail(url=settings.sprite_animated(species.id, shiny=shiny))
            await channel.send(embed=emb)
        except Exception:
            log.exception("Falha ao anunciar captura rara")

    async def _prefix_block_check(self, ctx: commands.Context) -> bool:
        # Slash (/menu, /start...) sempre passa — é o jeito privado de jogar.
        if ctx.interaction is not None:
            return True
        if ctx.guild is None:
            return True
        # admins/dono mantêm o prefixo para gerenciar
        if await self.is_owner(ctx.author):
            return True
        if ctx.author.guild_permissions.manage_guild:
            return True
        if ctx.cog and ctx.cog.qualified_name in ("Administração", "Dono"):
            return True
        # poucos comandos seguem por prefixo p/ todos (ex.: captura de spawn)
        if ctx.command and ctx.command.qualified_name in PREFIX_KEEP_FOR_USERS:
            return True
        raise PrefixDisabled()

    async def _channel_lock_check(self, ctx: commands.Context) -> bool:
        # DMs passam; comandos de admin/dono e utilitários passam em qualquer canal.
        # OBS: o dono NÃO é mais isento dos comandos de JOGO — assim a trava de canal
        # vale pra todos (incluindo você), e dá pra testar de verdade. Admin segue livre.
        if ctx.guild is None:
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
        if isinstance(error, PrefixDisabled):
            # tira o spam: apaga o comando do jogador e dá um toque que some sozinho
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            try:
                await ctx.send(
                    f"🔒 {ctx.author.mention}, agora é só pelo **/menu** (privado, só você vê)! "
                    f"Digite **/menu** para jogar. 🎮",
                    delete_after=8,
                )
            except discord.HTTPException:
                pass
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
