"""Exploração: p!explore — procure pokémon e escolha Capturar / Batalhar / Ignorar."""
from __future__ import annotations

import random

import discord
from discord.ext import commands

from config import settings
from bot.data.items import best_ball
from bot.data.pokemon_data import POKEDEX, Species
from bot.data.types import TYPE_EMOJI, type_color
from bot.database.db import session_scope
from bot.utils import embeds, helpers
from bot.utils.progression import bump_quest, check_achievements
from bot.utils.rarity import (
    RARITY_EMOJI,
    catch_coin_reward,
    pick_spawn_species,
    rarity_label,
    roll_shiny,
)

# Chance base de captura por raridade (quanto mais raro, mais difícil)
CATCH_CHANCE: dict[str, float] = {
    "common": 0.85,
    "uncommon": 0.65,
    "rare": 0.40,
    "superrare": 0.22,
    "legendary": 0.08,
    "mythical": 0.04,
}

# Bônus de chance (aditivo) por pokébola — consumida na tentativa
BALL_CATCH_BONUS: dict[str, float] = {
    "greatball": 0.15,
    "ultraball": 0.30,
    "masterball": 1.0,   # garante
}

LOCATIONS = [
    "Floresta de Viridian", "Rota 1", "Caverna Escura", "Monte Lua",
    "Praia de Pallet", "Túnel Rocha", "Estrada Vitória", "Campos de Kanto",
    "Pântano Sombrio", "Cume Nevado", "Ruínas Antigas", "Bosque Encantado",
]


async def do_capture(
    bot, explorer_id: int, species: Species, level: int, shiny: bool,
    iv_rolls: int = 1, iv_floor: int = 0,
):
    """Persiste a captura e devolve (poke_idx, coins, new_dex, conquistas)."""
    async with session_scope() as session:
        user = await helpers.fetch_user(session, explorer_id)
        poke = await helpers.create_pokemon(
            session, user, species, level=level, shiny=shiny,
            iv_rolls=iv_rolls, iv_floor=iv_floor,
        )
        coins = catch_coin_reward(species, shiny, settings.catch_coins_min, settings.catch_coins_max)
        user.coins += coins
        user.total_caught += 1
        if shiny:
            user.total_shiny += 1
        helpers.grant_trainer_xp(user, settings.catch_xp)
        new_dex = await helpers.update_pokedex(session, user.id, species.id, seen=1, caught=1)
        bump_quest(user, "catch", 1)
        newly = check_achievements(user)
        user.coins += sum(a.reward_coins for a in newly)
        idx = poke.idx
        iv_pct = poke.iv_percent
    return idx, coins, new_dex, newly, iv_pct


def encounter_embed(species: Species, shiny: bool, level: int, location: str,
                    state: str = "open") -> discord.Embed:
    color = settings.color_shiny if shiny else type_color(species.types)
    name = ("✨ " if shiny else "") + species.name
    types = " ".join(f"{TYPE_EMOJI.get(t,'')} {t.title()}" for t in species.types)
    emb = discord.Embed(color=color)
    if state == "open":
        emb.title = f"🌿 Um {name} selvagem apareceu!"
        emb.description = (
            f"📍 *{location}*\n\n"
            f"**{name}** • Nv {level}\n"
            f"{types} • {RARITY_EMOJI.get(species.rarity,'')} {rarity_label(species.rarity)}\n\n"
            f"O que você deseja fazer?"
        )
    emb.set_image(url=settings.sprite(species.id, shiny=shiny, official=True))
    return emb


class EncounterView(discord.ui.View):
    def __init__(self, cog: "Explore", ctx, species: Species, shiny: bool, level: int,
                 location: str):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.explorer_id = ctx.author.id
        self.species = species
        self.shiny = shiny
        self.level = level
        self.location = location
        self.message: discord.Message | None = None
        self.resolved = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.explorer_id:
            await interaction.response.send_message(
                "Esse encontro é de outro treinador! Use `p!explore` para o seu.",
                ephemeral=True,
            )
            return False
        return True

    def _finish_embed(self, title: str, color: int, extra: str = "") -> discord.Embed:
        name = ("✨ " if self.shiny else "") + self.species.name
        emb = discord.Embed(title=title, color=color,
                            description=f"**{name}** (Nv {self.level})\n{extra}")
        emb.set_thumbnail(url=settings.sprite(self.species.id, shiny=self.shiny))
        return emb

    # ---------------- Capturar ----------------
    @discord.ui.button(label="Capturar", emoji="🎯", style=discord.ButtonStyle.success)
    async def capturar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.resolved:
            return
        self.resolved = True
        for c in self.children:
            c.disabled = True

        # chance base + bônus de pokébola (consumida na tentativa)
        chance = CATCH_CHANCE.get(self.species.rarity, 0.5)
        iv_rolls, iv_floor, shiny = 1, 0, self.shiny
        ball_txt = ""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, interaction.user.id)
            inv = await helpers.get_inventory(session, user.id)
            ball = best_ball(inv)
            if ball is not None:
                await helpers.take_item(session, user.id, ball.key, 1)
                chance += BALL_CATCH_BONUS.get(ball.key, 0.0)
                iv_rolls, iv_floor = ball.catch_iv_rolls, ball.min_iv_floor
                if not shiny:
                    shiny = roll_shiny(settings.shiny_chance, ball.shiny_bonus)
                ball_txt = f" (usou {ball.emoji} {ball.name})"

        success = random.random() < min(chance, 1.0)
        if not success:
            emb = self._finish_embed(
                "💨 Quase!", settings.color_error,
                f"O **{self.species.name}** se soltou e fugiu!{ball_txt}\n"
                f"Chance era de {int(min(chance,1.0)*100)}%.",
            )
            await interaction.response.edit_message(embed=emb, view=self)
            self.stop()
            return

        idx, coins, new_dex, newly, iv_pct = await do_capture(
            self.cog.bot, interaction.user.id, self.species, self.level, shiny,
            iv_rolls, iv_floor,
        )
        extra = (
            f"📊 IV: **{iv_pct:.1f}%** • 💰 +{coins} PokéCoins{ball_txt}\n"
            f"Adicionado como **#{idx}**."
        )
        if new_dex:
            extra += "\n📕 Novo registro na Pokédex!"
        if shiny:
            extra += "\n✨ **SHINY!**"
        emb = self._finish_embed(f"🎉 Você capturou {self.species.name}!", settings.color_success, extra)
        await interaction.response.edit_message(embed=emb, view=self)
        if newly:
            await self.ctx.send(embed=embeds.ok_embed(
                "Conquista desbloqueada!",
                "\n".join(f"🏆 {a.name} (+{a.reward_coins} 🪙)" for a in newly),
            ))
        self.stop()

    # ---------------- Batalhar ----------------
    @discord.ui.button(label="Batalhar", emoji="⚔️", style=discord.ButtonStyle.primary)
    async def batalhar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.resolved:
            return
        battle_cog = self.cog.bot.get_cog("Batalha")
        if battle_cog is None:
            await interaction.response.send_message("Sistema de batalha indisponível.", ephemeral=True)
            return

        p1_team, err = await battle_cog.load_team(self.ctx, interaction.user)
        if not p1_team:
            await interaction.response.send_message(
                f"⚠️ {err}\nVocê pode **Capturar** sem batalhar.", ephemeral=True
            )
            return

        # consome o encontro e inicia a batalha
        self.resolved = True
        for c in self.children:
            c.disabled = True
        emb = self._finish_embed("⚔️ Batalha iniciada!", settings.color_info,
                                 "Vença para capturar o pokémon!")
        await interaction.response.edit_message(embed=emb, view=self)
        self.stop()

        from bot.cogs.battle import build_wild_mon
        p2_team = [build_wild_mon(self.species, self.level, shiny=self.shiny)]
        species, level, shiny, explorer_id = self.species, self.level, self.shiny, self.explorer_id
        cog, ctx = self.cog, self.ctx

        async def on_finish(winner, loser):
            if winner.owner_id != explorer_id:
                await ctx.send(embed=embeds.info_text(
                    f"O **{species.name}** selvagem te derrotou e fugiu... 💨",
                ))
                return
            idx, coins, new_dex, newly, iv_pct = await do_capture(
                cog.bot, explorer_id, species, level, shiny
            )
            extra = (f"Após a vitória, você capturou **{species.name}**!\n"
                     f"📊 IV: {iv_pct:.1f}% • Adicionado como #{idx}.")
            if new_dex:
                extra += "\n📕 Novo registro na Pokédex!"
            emb = discord.Embed(title=f"🎉 {species.name} capturado!", description=extra,
                                color=settings.color_success)
            emb.set_thumbnail(url=settings.sprite(species.id, shiny=shiny))
            await ctx.send(embed=emb)
            if newly:
                await ctx.send(embed=embeds.ok_embed(
                    "Conquista desbloqueada!",
                    "\n".join(f"🏆 {a.name} (+{a.reward_coins} 🪙)" for a in newly),
                ))

        await battle_cog.launch_battle(ctx, p1_team, p2_team, explorer_id, None, on_finish=on_finish)

    # ---------------- Ignorar ----------------
    @discord.ui.button(label="Ignorar", emoji="🏃", style=discord.ButtonStyle.secondary)
    async def ignorar(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if self.resolved:
            return
        self.resolved = True
        for c in self.children:
            c.disabled = True
        emb = self._finish_embed("🏃 Você seguiu em frente.", settings.color_info,
                                 "Deixou o pokémon em paz.")
        await interaction.response.edit_message(embed=emb, view=self)
        self.stop()

    async def on_timeout(self) -> None:
        if self.resolved:
            return
        for c in self.children:
            c.disabled = True
        emb = self._finish_embed("💨 O pokémon foi embora...", settings.color_error,
                                 "Você demorou demais para decidir.")
        if self.message:
            try:
                await self.message.edit(embed=emb, view=self)
            except discord.HTTPException:
                pass


class Explore(commands.Cog, name="Exploração"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _encounter_level(self, explorer_id: int) -> int:
        """Nível do encontro, próximo ao pokémon selecionado do jogador."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, explorer_id)
            selected = await helpers.get_selected(session, user)
            base = selected.level if selected else random.randint(3, 12)
        return max(1, base + random.randint(-3, 4))

    @commands.command(name="explore", aliases=["explorar", "ex", "adventure"])
    @commands.guild_only()
    @commands.cooldown(1, settings.explore_cooldown_seconds, commands.BucketType.user)
    async def explore(self, ctx: commands.Context) -> None:
        """Explore a região em busca de pokémon selvagens."""
        location = random.choice(LOCATIONS)
        roll = random.random()

        # 1) não achou nada
        if roll < settings.explore_nothing_chance:
            flavores = [
                "A área estava silenciosa... nenhum pokémon à vista.",
                "Você ouviu um barulho na moita, mas nada apareceu.",
                "Apenas o vento. Tente novamente em instantes.",
                "Você encontrou pegadas, mas o rastro acabou.",
            ]
            await ctx.send(embed=embeds.info_text(
                f"📍 *{location}*\n{random.choice(flavores)}",
                title="🔍 Exploração",
            ))
            return

        # 2) achou moedas
        if roll < settings.explore_nothing_chance + settings.explore_coins_chance:
            coins = random.randint(settings.explore_coins_min, settings.explore_coins_max)
            async with session_scope() as session:
                user = await helpers.fetch_user(session, ctx.author.id)
                user.coins += coins
            await ctx.send(embed=embeds.ok_embed(
                "💰 Você achou um tesouro!",
                f"📍 *{location}*\nEncontrou **{coins} PokéCoins** no chão!",
            ))
            return

        # 3) encontro com pokémon
        species = pick_spawn_species()
        shiny = roll_shiny(settings.shiny_chance)
        level = await self._encounter_level(ctx.author.id)

        # registra como "visto" na Pokédex
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            await helpers.update_pokedex(session, user.id, species.id, seen=1, caught=0)

        view = EncounterView(self, ctx, species, shiny, level, location)
        view.message = await ctx.send(
            embed=encounter_embed(species, shiny, level, location), view=view
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Explore(bot))
