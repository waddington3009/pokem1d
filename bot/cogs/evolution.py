"""Sistema de evolução: por nível, por pedra, com confirmação e cancelamento."""
from __future__ import annotations

import discord
from discord.ext import commands

from config import settings
from bot.data.pokemon_data import POKEDEX, EvolutionStep, Species
from bot.database.db import session_scope
from bot.database.models import Pokemon
from bot.utils import embeds, helpers
from bot.utils.confirm import Confirm
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
            step = species.can_evolve_by_level(poke.level)

            if step is None:
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

            target = POKEDEX.get(step.to)
            idx, shiny = poke.idx, poke.shiny

        # confirmação (permite cancelar)
        view = Confirm(ctx.author.id, confirm_label="Evoluir!", cancel_label="Cancelar")
        emb = embeds.info_text(
            f"Deseja evoluir **{species.name}** (#{idx}) para **{target.name}**?",
            title="Confirmar evolução",
        )
        emb.set_thumbnail(url=settings.sprite_animated(target.id, shiny=shiny))
        view.message = await ctx.send(embed=emb, view=view)
        await view.wait()

        if not view.value:
            await ctx.send(embed=embeds.info_text("Evolução cancelada. 🛑"))
            return

        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
            species = POKEDEX.get(poke.species_id)
            step = species.can_evolve_by_level(poke.level)
            if step is None:
                await ctx.send(embed=embeds.err_embed("A evolução não é mais possível."))
                return
            new_species = await perform_evolution(session, poke, step)
            await helpers.update_pokedex(session, user.id, new_species.id, seen=1, caught=1)
            bump_quest(user, "evolve", 1)

        await ctx.send(embed=evolution_embed(species, new_species, shiny, idx))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Evolution(bot))
