"""Sistema de spawn: conta mensagens, faz aparecer pokémon e os despawna."""
from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

import discord
from discord.ext import commands, tasks

from config import settings
from bot.data.items import get_item
from bot.data.pokemon_data import POKEDEX, Species
from bot.database.db import get_or_create_guild, session_scope
from bot.utils import embeds, helpers
from bot.utils.rarity import pick_spawn_species, roll_shiny


@dataclass
class ActiveSpawn:
    species: Species
    shiny: bool
    channel_id: int
    guild_id: int
    message_id: int | None = None
    spawned_at: float = field(default_factory=time.time)


@dataclass
class LootBox:
    reward: tuple              # ("coins", n) | ("item", key, qty)
    channel_id: int
    message_id: int | None = None
    spawned_at: float = field(default_factory=time.time)


# Tabela de itens do loot: (item_key, qtd_min, qtd_max, peso)
LOOT_ITEMS = [
    ("greatball", 2, 6, 28),
    ("ultraball", 1, 3, 16),
    ("rare-candy", 1, 4, 16),
    ("xp-booster", 2, 6, 16),
    ("incense", 1, 1, 8),
    ("fire-stone", 1, 1, 3),
    ("water-stone", 1, 1, 3),
    ("thunder-stone", 1, 1, 3),
    ("masterball", 1, 1, 2),
]


def roll_loot_reward() -> tuple:
    """Sorteia o prêmio da caixa: moedas (>1000) ou um item."""
    if random.random() < settings.loot_coins_chance:
        return ("coins", random.randint(settings.loot_coins_min, settings.loot_coins_max))
    key, lo, hi, _ = random.choices(LOOT_ITEMS, weights=[x[3] for x in LOOT_ITEMS], k=1)[0]
    return ("item", key, random.randint(lo, hi))


class Spawning(commands.Cog, name="Spawn"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # spawns ativos por canal (acessado pela cog de captura)
        bot.active_spawns: dict[int, ActiveSpawn] = {}
        # caixas de loot ativas por canal
        bot.active_loot: dict[int, LootBox] = {}
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
        # cooldown e spawn/loot já ativo
        if time.time() - self.last_spawn.get(target.id, 0) < settings.spawn_cooldown_seconds:
            return
        if target.id in self.bot.active_spawns or target.id in self.bot.active_loot:
            return

        # rola: às vezes cai uma caixa de loot em vez de um pokémon
        if random.random() < settings.loot_chance:
            await self.spawn_loot(target)
        else:
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
    async def spawn_loot(self, channel: discord.TextChannel) -> LootBox | None:
        """Faz uma caixa de loot cair no canal."""
        reward = roll_loot_reward()
        embed = discord.Embed(
            title="📦 Uma caixa de mantimentos caiu do céu!",
            description="Rápido! Use **`/coletar`** para abrir antes dos outros! 🎁",
            color=settings.color_default,
        )
        embed.set_image(url=settings.loot_image_url)
        embed.set_footer(text="O primeiro a coletar leva tudo!")
        try:
            msg = await channel.send(embed=embed)
        except discord.Forbidden:
            return None
        box = LootBox(reward=reward, channel_id=channel.id, message_id=msg.id)
        self.bot.active_loot[channel.id] = box
        self.last_spawn[channel.id] = time.time()
        return box

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
                embed.set_thumbnail(url=settings.sprite_animated(spawn.species.id, shiny=spawn.shiny))
                await channel.send(embed=embed)
            except discord.HTTPException:
                pass

        # expira caixas de loot não coletadas
        expired_loot = [
            cid for cid, b in list(self.bot.active_loot.items())
            if now - b.spawned_at > settings.loot_despawn_seconds
        ]
        for cid in expired_loot:
            box = self.bot.active_loot.pop(cid, None)
            channel = self.bot.get_channel(cid)
            if box is None or channel is None:
                continue
            try:
                await channel.send(embed=discord.Embed(
                    description="📦 A caixa de mantimentos desapareceu... ninguém coletou a tempo.",
                    color=settings.color_error,
                ))
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
        # apaga o comando para não revelar o nome (evento surpresa)
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        species = POKEDEX.by_name(nome) if nome else None
        if nome and species is None:
            await ctx.send(embed=embeds.err_embed(f"Espécie `{nome}` não encontrada."))
            return
        self.bot.active_spawns.pop(ctx.channel.id, None)
        await self.spawn_pokemon(ctx.channel, species)

    @commands.command(name="forceloot", aliases=["floot"])
    @commands.is_owner()
    async def forceloot(self, ctx: commands.Context) -> None:
        """[Owner] Força uma caixa de loot a cair no canal."""
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        self.bot.active_loot.pop(ctx.channel.id, None)
        await self.spawn_loot(ctx.channel)

    # ------------------------------------------------------------------
    @commands.hybrid_command(name="coletar", aliases=["loot", "collect", "abrir"])
    @commands.guild_only()
    @commands.cooldown(1, 1.5, commands.BucketType.user)
    async def coletar(self, ctx: commands.Context) -> None:
        """Coleta a caixa de loot ativa no canal (o primeiro leva!)."""
        box = self.bot.active_loot.get(ctx.channel.id)
        if box is None:
            await ctx.send(embed=embeds.err_embed(
                "Não há nenhuma caixa de loot por aqui agora. Fique de olho no chat!"))
            return
        # remove imediatamente (anti-corrida): só o primeiro coleta
        self.bot.active_loot.pop(ctx.channel.id, None)

        reward = box.reward
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            if reward[0] == "coins":
                user.coins += reward[1]
                desc = f"💰 **{reward[1]:,} PokéCoins**!"
            else:
                _, key, qty = reward
                await helpers.add_item(session, user.id, key, qty)
                it = get_item(key)
                emoji = it.emoji if it else "🎁"
                nome = it.name if it else key
                desc = f"{emoji} **{qty}× {nome}**!"

        await ctx.send(embed=embeds.ok_embed(
            f"🎁 {ctx.author.display_name} abriu a caixa!", f"Recebeu: {desc}"))

        if box.message_id:
            try:
                msg = await ctx.channel.fetch_message(box.message_id)
                await msg.edit(embed=discord.Embed(
                    description=f"📦 Caixa coletada por **{ctx.author.display_name}**! {desc}",
                    color=settings.color_success,
                ))
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Spawning(bot))
