"""Exploração: p!explore — procure pokémon e escolha Capturar / Batalhar / Ignorar."""
from __future__ import annotations

import random

import discord
from discord.ext import commands

from config import settings
from bot.data.items import get_item
from bot.data.pokemon_data import POKEDEX, Species
from bot.data.types import TYPE_EMOJI, type_color
from bot.database.db import session_scope
from bot.utils import embeds, helpers
from bot.utils.explore_scene import render_explore_scene
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
    "pokeball": 0.0,     # base
    "greatball": 0.15,
    "ultraball": 0.30,
    "masterball": 1.0,   # garante
}
BALL_ORDER = ["pokeball", "greatball", "ultraball", "masterball"]

LOCATIONS = [
    "Floresta de Viridian", "Rota 1", "Caverna Escura", "Monte Lua",
    "Praia de Pallet", "Túnel Rocha", "Estrada Vitória", "Campos de Kanto",
    "Pântano Sombrio", "Cume Nevado", "Ruínas Antigas", "Bosque Encantado",
]

# Bônus de nível por raridade (raros/lendários aparecem um pouco mais fortes)
_LEVEL_RARITY_BONUS = {"rare": 2, "superrare": 4, "legendary": 6, "mythical": 8}


def roll_encounter_level(species: Species, lead_level: int) -> int:
    """Nível do selvagem — escala com o pokémon líder do jogador (moderado).

    Fica em torno de 90% do nível do seu líder (com variação), mais um bônus
    por raridade. Assim, quanto mais forte você fica, mais fortes os selvagens —
    mas nunca absurdamente acima de você. Esse MESMO nível é usado no card e na
    batalha (sem inconsistência).
    """
    base = round(max(1, lead_level) * 0.9) + random.randint(-3, 3)
    return max(1, min(100, base + _LEVEL_RARITY_BONUS.get(species.rarity, 0)))


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
                    state: str = "open", scene: bool = False) -> discord.Embed:
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
    if scene:
        # cena composta (pokémon na floresta) enviada como anexo
        emb.set_image(url="attachment://encounter.png")
    else:
        emb.set_image(url=settings.sprite(species.id, shiny=shiny, official=True))
    return emb


class EncounterView(discord.ui.View):
    def __init__(self, cog: "Explore", ctx, species: Species, shiny: bool, level: int,
                 location: str, scene: bool = False):
        super().__init__(timeout=60)
        self.cog = cog
        self.ctx = ctx
        self.explorer_id = ctx.author.id
        self.species = species
        self.shiny = shiny
        self.level = level
        self.location = location
        self.scene = scene
        self.message: discord.Message | None = None
        self.resolved = False
        self.phase = "main"          # "main" | "ball"
        self.owned: dict[str, int] = {}
        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.explorer_id:
            await interaction.response.send_message(
                "Esse encontro é de outro treinador! Use `p!explore` para o seu.",
                ephemeral=True,
            )
            return False
        return True

    # ---- construção dos botões ----
    def _build(self) -> None:
        self.clear_items()
        if self.phase == "main":
            self.add_item(EncounterButton("Capturar", "🎯", discord.ButtonStyle.success, "capturar", self))
            self.add_item(EncounterButton("Batalhar", "⚔️", discord.ButtonStyle.primary, "batalhar", self))
            self.add_item(EncounterButton("Ignorar", "🏃", discord.ButtonStyle.secondary, "ignorar", self))
        elif self.phase == "ball":
            for key in BALL_ORDER:
                if self.owned.get(key, 0) > 0:
                    self.add_item(BallButton(key, self.owned[key], self))
            self.add_item(EncounterButton("Voltar", "↩️", discord.ButtonStyle.secondary, "voltar", self, row=1))

    def _chance_for(self, ball_key: str) -> float:
        base = CATCH_CHANCE.get(self.species.rarity, 0.5)
        return min(base + BALL_CATCH_BONUS.get(ball_key, 0.0), 1.0)

    def _finish_embed(self, title: str, color: int, extra: str = "") -> discord.Embed:
        name = ("✨ " if self.shiny else "") + self.species.name
        emb = discord.Embed(title=title, color=color,
                            description=f"**{name}** (Nv {self.level})\n{extra}")
        emb.set_thumbnail(url=settings.sprite_animated(self.species.id, shiny=self.shiny))
        return emb

    def _ball_embed(self) -> discord.Embed:
        name = ("✨ " if self.shiny else "") + self.species.name
        emb = discord.Embed(
            title=f"🎯 Capturar {name}",
            description="Escolha a **pokébola** para usar — a chance varia conforme a bola:",
            color=type_color(self.species.types),
        )
        emb.set_thumbnail(url=settings.sprite_animated(self.species.id, shiny=self.shiny))
        return emb

    # ---- ações ----
    async def on_main(self, interaction: discord.Interaction, action: str) -> None:
        if self.resolved:
            return
        if action == "capturar":
            async with session_scope() as session:
                user = await helpers.fetch_user(session, self.explorer_id)
                inv = await helpers.get_inventory(session, user.id)
            self.owned = {k: inv.get(k, 0) for k in BALL_ORDER if inv.get(k, 0) > 0}
            if not self.owned:
                await interaction.response.send_message(
                    "🎒 Você não tem pokébolas! Compre na `p!shop` (ou escolha **Batalhar**).",
                    ephemeral=True,
                )
                return
            self.phase = "ball"
            self._build()
            await interaction.response.edit_message(embed=self._ball_embed(), view=self)
        elif action == "voltar":
            self.phase = "main"
            self._build()
            # sem 'attachments': mantém a cena já anexada na mensagem original
            await interaction.response.edit_message(
                embed=encounter_embed(self.species, self.shiny, self.level, self.location,
                                      scene=self.scene), view=self)
        elif action == "batalhar":
            await self._do_battle(interaction)
        elif action == "ignorar":
            self.resolved = True
            self.clear_items()
            emb = self._finish_embed("🏃 Você seguiu em frente.", settings.color_info,
                                     "Deixou o pokémon em paz.")
            await interaction.response.edit_message(embed=emb, view=self)
            self.stop()

    async def on_ball(self, interaction: discord.Interaction, ball_key: str) -> None:
        if self.resolved:
            return
        self.resolved = True
        self.clear_items()
        item = get_item(ball_key)
        chance = self._chance_for(ball_key)
        shiny = self.shiny

        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.explorer_id)
            ok = await helpers.take_item(session, user.id, ball_key, 1)
        if not ok:
            await interaction.response.edit_message(
                embed=self._finish_embed("Ops!", settings.color_error, "Você não tinha essa pokébola."),
                view=self)
            self.stop()
            return

        if not shiny:
            shiny = roll_shiny(settings.shiny_chance, item.shiny_bonus)

        if random.random() >= chance:
            emb = self._finish_embed(
                "💨 Quase!", settings.color_error,
                f"O **{self.species.name}** se soltou e fugiu! (usou {item.emoji} {item.name})\n"
                f"Chance era de **{int(chance*100)}%**.")
            await interaction.response.edit_message(embed=emb, view=self)
            self.stop()
            return

        idx, coins, new_dex, newly, iv_pct = await do_capture(
            self.cog.bot, self.explorer_id, self.species, self.level, shiny,
            item.catch_iv_rolls, item.min_iv_floor)
        extra = (f"📊 IV: **{iv_pct:.1f}%** • 💰 +{coins} PokéCoins (usou {item.emoji} {item.name})\n"
                 f"Adicionado como **#{idx}**.")
        if new_dex:
            extra += "\n📕 Novo registro na Pokédex!"
        if shiny:
            extra += "\n✨ **SHINY!**"
        emb = self._finish_embed(f"🎉 Você capturou {self.species.name}!", settings.color_success, extra)
        await interaction.response.edit_message(embed=emb, view=self)
        if newly:
            await self.ctx.send(embed=embeds.ok_embed(
                "Conquista desbloqueada!",
                "\n".join(f"🏆 {a.name} (+{a.reward_coins} 🪙)" for a in newly)))
        self.stop()

    async def _do_battle(self, interaction: discord.Interaction) -> None:
        battle_cog = self.cog.bot.get_cog("Batalha")
        if battle_cog is None:
            await interaction.response.send_message("Sistema de batalha indisponível.", ephemeral=True)
            return
        p1_team, err = await battle_cog.load_team(self.ctx, interaction.user)
        if not p1_team:
            await interaction.response.send_message(
                f"⚠️ {err}\nVocê pode **Capturar** com uma pokébola.", ephemeral=True)
            return

        self.resolved = True
        self.clear_items()
        emb = self._finish_embed("⚔️ Batalha iniciada!", settings.color_info,
                                 "Lute por **XP e moedas**! (a batalha não captura o pokémon)")
        await interaction.response.edit_message(embed=emb, view=self)
        self.stop()

        from bot.cogs.battle import build_wild_mon
        # usa o MESMO nível mostrado no card (sem inconsistência)
        p2_team = [build_wild_mon(self.species, self.level, shiny=self.shiny)]
        species, explorer_id, ctx = self.species, self.explorer_id, self.ctx

        async def on_finish(winner, loser):
            if winner.owner_id == explorer_id:
                await ctx.send(embed=embeds.ok_embed(
                    "Vitória! 🏆",
                    f"Você derrotou o **{species.name}** selvagem e ele fugiu. "
                    f"Recompensas de batalha aplicadas! Para colecioná-lo, use **Capturar** num próximo encontro."))
            else:
                await ctx.send(embed=embeds.info_text(f"O **{species.name}** selvagem te derrotou... 💨"))

        await battle_cog.launch_battle(ctx, p1_team, p2_team, explorer_id, None, on_finish=on_finish)

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


class EncounterButton(discord.ui.Button):
    def __init__(self, label, emoji, style, action, view: EncounterView, row: int = 0):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self.action = action
        self._ev = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._ev.on_main(interaction, self.action)


class BallButton(discord.ui.Button):
    def __init__(self, ball_key: str, qty: int, view: EncounterView):
        item = get_item(ball_key)
        chance = view._chance_for(ball_key)
        super().__init__(
            label=f"{item.name} (×{qty}) • {int(chance * 100)}%",
            emoji=item.emoji, style=discord.ButtonStyle.success,
        )
        self.ball_key = ball_key
        self._ev = view

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._ev.on_ball(interaction, self.ball_key)


class Explore(commands.Cog, name="Exploração"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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
            emb = embeds.info_text(
                f"📍 *{location}*\n{random.choice(flavores)}", title="🔍 Exploração")
            buf = await render_explore_scene("nothing")
            file = discord.File(buf, filename="explore.png") if buf else None
            if file:
                emb.set_image(url="attachment://explore.png")
            await ctx.send(embed=emb, **({"file": file} if file else {}))
            return

        # 2) achou moedas
        if roll < settings.explore_nothing_chance + settings.explore_coins_chance:
            coins = random.randint(settings.explore_coins_min, settings.explore_coins_max)
            async with session_scope() as session:
                user = await helpers.fetch_user(session, ctx.author.id)
                user.coins += coins
            emb = embeds.ok_embed(
                "💰 Você achou um tesouro!",
                f"📍 *{location}*\nEncontrou **{coins} PokéCoins** no chão!")
            buf = await render_explore_scene("coins")
            file = discord.File(buf, filename="explore.png") if buf else None
            if file:
                emb.set_image(url="attachment://explore.png")
            await ctx.send(embed=emb, **({"file": file} if file else {}))
            return

        # 3) encontro com pokémon
        species = pick_spawn_species()
        shiny = roll_shiny(settings.shiny_chance)

        # nível escala com o LÍDER do time (party[0] = o pokémon selecionado),
        # que é o mesmo que batalha primeiro — tudo consistente com o p!select
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            party = list(user.party or [])
            lead_level = None
            if party:
                lead = await helpers.get_pokemon_by_idx(session, user.id, party[0])
                if lead:
                    lead_level = lead.level
            if lead_level is None:
                selected = await helpers.get_selected(session, user)
                lead_level = selected.level if selected else 5
            await helpers.update_pokedex(session, user.id, species.id, seen=1, caught=0)
        level = roll_encounter_level(species, lead_level)

        # cena: o pokémon em pé na floresta (fundo). Cai pro artwork se falhar.
        buf = await render_explore_scene("pokemon", species, shiny)
        file = discord.File(buf, filename="encounter.png") if buf else None
        view = EncounterView(self, ctx, species, shiny, level, location, scene=file is not None)
        view.message = await ctx.send(
            embed=encounter_embed(species, shiny, level, location, scene=file is not None),
            view=view, **({"file": file} if file else {}),
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Explore(bot))
