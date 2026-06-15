"""Sistema de evolução: por nível, por pedra, com confirmação e cancelamento."""
from __future__ import annotations

import discord
from discord.ext import commands

from config import settings
from bot.data.pokemon_data import POKEDEX, EvolutionStep, Species
from bot.database.db import session_scope
from bot.database.models import Pokemon
from bot.utils import embeds, helpers
from bot.utils.progression import bump_quest


def evolution_embed(before: Species, after: Species, shiny: bool, idx: int) -> discord.Embed:
    emb = discord.Embed(
        title="✨ Evolução!",
        description=f"Seu **{before.name}** (#{idx}) evoluiu para **{after.name}**!",
        color=settings.color_shiny if shiny else settings.color_success,
    )
    emb.set_thumbnail(url=settings.sprite_animated(after.id, shiny=shiny))
    return emb


async def perform_evolution(session, poke: Pokemon, step: EvolutionStep) -> Species:
    """Aplica a evolução ao pokémon (muda a espécie). Retorna a nova espécie."""
    new_species = POKEDEX.get(step.to)
    poke.species_id = new_species.id
    return new_species


class EvolveChoiceView(discord.ui.View):
    """Botão por forma elegível (1 = confirmação simples; 2+ = evolução paralela)."""

    def __init__(self, author_id: int, steps: list[EvolutionStep]):
        super().__init__(timeout=60)
        self.author_id = author_id
        self.value: EvolutionStep | None = None
        self.message: discord.Message | None = None
        single = len(steps) == 1
        for st in steps:
            target = POKEDEX.get(st.to)
            label = f"Evoluir para {target.name}" if single else target.name
            self.add_item(EvolveTargetButton(st, label))
        self.add_item(EvolveCancelButton())

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Essa evolução não é sua. 😉", ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class EvolveTargetButton(discord.ui.Button):
    def __init__(self, step: EvolutionStep, label: str):
        super().__init__(label=label, emoji="✨", style=discord.ButtonStyle.success)
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EvolveChoiceView = self.view
        view.value = self.step
        for c in view.children:
            c.disabled = True
        await interaction.response.edit_message(view=view)
        view.stop()


class EvolveCancelButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Cancelar", emoji="🛑", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: EvolveChoiceView = self.view
        view.value = None
        for c in view.children:
            c.disabled = True
        await interaction.response.edit_message(view=view)
        view.stop()


class Evolution(commands.Cog, name="Evolução"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="evolve", aliases=["evoluir"])
    @commands.guild_only()
    async def evolve(self, ctx: commands.Context, numero: int | None = None) -> None:
        """Evolui um pokémon elegível por nível. Uso: evolve [#] (vazio = selecionado)."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            if numero is None:
                poke = await helpers.get_selected(session, user)
            else:
                poke = await helpers.get_pokemon_by_idx(session, user.id, numero)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(
                    "Pokémon não encontrado. Use `evolve <número>` ou selecione um."
                ))
                return

            species = POKEDEX.get(poke.species_id)
            steps = species.eligible_level_evos(poke.level)

            if not steps:
                # informa o requisito mais próximo, se houver
                level_evos = [e for e in species.evolutions if e.method == "level"]
                stone_evos = [e for e in species.evolutions if e.method == "stone"]
                if level_evos:
                    need = min(e.level for e in level_evos)
                    msg = f"**{species.name}** evolui no nível **{need}** (atual: {poke.level})."
                elif stone_evos:
                    pedras = ", ".join(f"`{e.stone}-stone`" for e in stone_evos)
                    msg = f"**{species.name}** evolui usando uma pedra: {pedras} (use `use <pedra>`)."
                else:
                    msg = f"**{species.name}** não evolui mais."
                await ctx.send(embed=embeds.err_embed(msg, title="Ainda não pode evoluir"))
                return

            idx, shiny, before_name = poke.idx, poke.shiny, species.name

        # menu de escolha (1 forma = confirmação; 2+ = evolução paralela)
        view = EvolveChoiceView(ctx.author.id, steps)
        if len(steps) > 1:
            alvos = ", ".join(f"**{POKEDEX.get(s.to).name}**" for s in steps)
            emb = embeds.info_text(
                f"**{before_name}** (#{idx}) pode seguir **{len(steps)} caminhos** de evolução: "
                f"{alvos}.\nEscolha para qual quer evoluir:",
                title="🔀 Evolução paralela — escolha!",
            )
        else:
            target = POKEDEX.get(steps[0].to)
            emb = embeds.info_text(
                f"Deseja evoluir **{before_name}** (#{idx}) para **{target.name}**?",
                title="Confirmar evolução",
            )
            emb.set_thumbnail(url=settings.sprite_animated(target.id, shiny=shiny))
        view.message = await ctx.send(embed=emb, view=view)
        await view.wait()

        if view.value is None:
            await ctx.send(embed=embeds.info_text("Evolução cancelada. 🛑"))
            return
        chosen_to = view.value.to

        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
            species = POKEDEX.get(poke.species_id)
            # revalida: a forma escolhida ainda precisa estar elegível
            step = next((s for s in species.eligible_level_evos(poke.level) if s.to == chosen_to), None)
            if step is None:
                await ctx.send(embed=embeds.err_embed("A evolução não é mais possível."))
                return
            new_species = await perform_evolution(session, poke, step)
            await helpers.update_pokedex(session, user.id, new_species.id, seen=1, caught=1)
            bump_quest(user, "evolve", 1)

        await ctx.send(embed=evolution_embed(species, new_species, shiny, idx))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Evolution(bot))
