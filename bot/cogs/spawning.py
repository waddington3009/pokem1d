"""Sistema de spawn: conta mensagens, faz aparecer pokémon e os despawna."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands, tasks

from config import settings
from bot.data.pokemon_data import POKEDEX, Species
from bot.database.db import get_or_create_guild, session_scope
from bot.utils import embeds
from bot.utils.rarity import pick_spawn_species, roll_shiny


@dataclass
class ActiveSpawn:
    species: Species
    shiny: bool
    channel_id: int
    guild_id: int
    message_id: int | None = None
    spawned_at: float = field(default_factory=time.time)


class Spawning(commands.Cog, name="Spawn"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # spawns ativos por canal (acessado pela cog de captura)
        bot.active_spawns: dict[int, ActiveSpawn] = {}
        # contadores e limiares de mensagens por canal
        self.counters: dict[int, int] = {}
        self.thresholds: dict[int, int] = {}
        # último spawn por canal (cooldown)
        self.last_spawn: dict[int, float] = {}
        # incensos ativos: channel_id -> timestamp de expiração
        self.lures: dict[int, float] = {}
        self.despawn_loop.start()

    def cog_unload(self) -> None:
        self.despawn_loop.cancel()

    # ------------------------------------------------------------------
    def _roll_threshold(self, channel_id: int) -> int:
        base = random.randint(settings.spawn_min_messages, settings.spawn_max_messages)
        # incenso reduz o limiar pela metade
        if self.lures.get(channel_id, 0) > time.time():
            base = max(3, base // 2)
        return base

    def add_lure(self, channel_id: int, minutes: int) -> None:
        self.lures[channel_id] = time.time() + minutes * 60

    # ------------------------------------------------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return

        channel_id = message.channel.id
        self.counters[channel_id] = self.counters.get(channel_id, 0) + 1
        threshold = self.thresholds.setdefault(channel_id, self._roll_threshold(channel_id))

        if self.counters[channel_id] < threshold:
            return

        # atingiu o limiar — tenta spawnar
        self.counters[channel_id] = 0
        self.thresholds[channel_id] = self._roll_threshold(channel_id)
        await self._try_spawn(message)

    async def _try_spawn(self, message: discord.Message) -> None:
        guild = message.guild
        async with session_scope() as session:
            cfg = await get_or_create_guild(session, guild.id)
            enabled = cfg.spawns_enabled
            redirect_id = cfg.redirect_channel_id
            blacklist = set(cfg.blacklist or [])
            game_channels = self.bot._merge_channels(cfg)

        if not enabled:
            return

        if game_channels:
            # com canais de jogo definidos: spawna no canal de atividade, se for um deles
            if message.channel.id not in game_channels:
                return
            target = message.channel
        else:
            # modo livre: redirecionamento tem prioridade, respeita a blacklist
            target = message.channel
            if redirect_id:
                ch = guild.get_channel(redirect_id)
                if ch is not None:
                    target = ch
            if target.id in blacklist:
                return
        # só spawna onde o bot pode enviar mensagem + embed (evita 403)
        me = target.guild.me
        if me is not None:
            perms = target.permissions_for(me)
            if not (perms.send_messages and perms.embed_links):
                return
        # cooldown e spawn já ativo
        if time.time() - self.last_spawn.get(target.id, 0) < settings.spawn_cooldown_seconds:
            return
        if target.id in self.bot.active_spawns:
            return

        await self.spawn_pokemon(target)

    # ------------------------------------------------------------------
    async def spawn_pokemon(
        self, channel: discord.TextChannel, species: Species | None = None
    ) -> ActiveSpawn | None:
        """Faz um pokémon aparecer no canal."""
        species = species or pick_spawn_species()
        shiny = roll_shiny(settings.shiny_chance)

        prefix = self.bot.prefix_cache.get(channel.guild.id, settings.default_prefix)
        embed = embeds.spawn_embed(species, shiny, prefix)

        try:
            msg = await channel.send(embed=embed)
        except discord.Forbidden:
            # sem permissão para postar neste canal — ignora silenciosamente
            return None
        spawn = ActiveSpawn(
            species=species, shiny=shiny, channel_id=channel.id,
            guild_id=channel.guild.id, message_id=msg.id,
        )
        self.bot.active_spawns[channel.id] = spawn
        self.last_spawn[channel.id] = time.time()
        return spawn

    # ------------------------------------------------------------------
    @tasks.loop(seconds=30)
    async def despawn_loop(self) -> None:
        """Remove spawns que ficaram tempo demais sem captura."""
        now = time.time()
        expired = [
            cid for cid, sp in list(self.bot.active_spawns.items())
            if now - sp.spawned_at > settings.spawn_despawn_seconds
        ]
        for cid in expired:
            spawn = self.bot.active_spawns.pop(cid, None)
            if spawn is None:
                continue
            channel = self.bot.get_channel(cid)
            if channel is None:
                continue
            try:
                embed = discord.Embed(
                    description=f"O **{spawn.species.name}** selvagem fugiu... 🍃",
                    color=settings.color_error,
                )
                embed.set_thumbnail(url=settings.sprite(spawn.species.id, shiny=spawn.shiny))
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

    @despawn_loop.before_loop
    async def before_despawn(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------
    @commands.command(name="forcespawn", aliases=["fspawn"])
    @commands.is_owner()
    async def forcespawn(self, ctx: commands.Context, *, nome: str | None = None) -> None:
        """[Owner] Força o spawn de um pokémon (opcionalmente por nome)."""
        species = POKEDEX.by_name(nome) if nome else None
        if nome and species is None:
            await ctx.send(embed=embeds.err_embed(f"Espécie `{nome}` não encontrada."))
            return
        self.bot.active_spawns.pop(ctx.channel.id, None)
        await self.spawn_pokemon(ctx.channel, species)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Spawning(bot))
