"""Inventário e uso de itens (pedras, boosters, incenso)."""
from __future__ import annotations

import discord
from discord.ext import commands

from config import settings
from bot.data.items import find_item, get_item
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.utils import embeds, helpers
from bot.utils.progression import bump_quest
from bot.utils.stats import apply_xp

CATEGORY_LABEL = {
    "ball": "🎯 Pokébolas",
    "stone": "💎 Pedras de Evolução",
    "lure": "🪔 Incensos",
    "booster": "📈 Boosters",
    "misc": "📦 Outros",
}


class Items(commands.Cog, name="Itens"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    @commands.command(name="bag", aliases=["inventory", "inv", "inventario", "mochila"])
    @commands.guild_only()
    async def bag(self, ctx: commands.Context) -> None:
        """Mostra os itens do seu inventário."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            inv = await helpers.get_inventory(session, user.id)

        if not inv:
            await ctx.send(embed=embeds.info_text(
                f"Seu inventário está vazio. Compre itens na `{ctx.prefix}shop`.",
                title="🎒 Inventário",
            ))
            return

        # agrupa por categoria
        grouped: dict[str, list[str]] = {}
        for key, qty in sorted(inv.items()):
            it = get_item(key)
            if it is None:
                continue
            grouped.setdefault(it.category, []).append(f"{it.emoji} **{it.name}** ×{qty}")

        emb = discord.Embed(title=f"🎒 Inventário de {ctx.author.display_name}", color=settings.color_info)
        for cat, label in CATEGORY_LABEL.items():
            if cat in grouped:
                emb.add_field(name=label, value="\n".join(grouped[cat]), inline=False)
        emb.set_footer(text=f"Use {ctx.prefix}use <item> [#pokémon]")
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="use", aliases=["usar"])
    @commands.guild_only()
    async def use(self, ctx: commands.Context, item: str, numero: int | None = None) -> None:
        """Usa um item. Uso: use <item> [#pokémon]."""
        it = find_item(item)
        if it is None:
            await ctx.send(embed=embeds.err_embed("Item desconhecido. Veja seu inventário com `bag`."))
            return

        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            inv = await helpers.get_inventory(session, user.id)
            if inv.get(it.key, 0) < 1:
                await ctx.send(embed=embeds.err_embed(f"Você não tem **{it.name}**."))
                return

            # ---- Incenso: afeta o canal, não um pokémon ----
            if it.category == "lure":
                spawning = self.bot.get_cog("Spawn")
                if spawning:
                    spawning.add_lure(ctx.channel.id, it.lure_minutes)
                await helpers.take_item(session, user.id, it.key, 1)
                await ctx.send(embed=embeds.ok_embed(
                    "Incenso ativado! 🪔",
                    f"Os spawns neste canal vão acelerar pelos próximos **{it.lure_minutes} min**.",
                ))
                return

            # ---- Demais itens: precisam de um pokémon alvo ----
            if numero is not None:
                poke = await helpers.get_pokemon_by_idx(session, user.id, numero)
            else:
                poke = await helpers.get_selected(session, user)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(
                    "Escolha um pokémon: `use <item> <#>` ou selecione um com `select`."
                ))
                return

            species = POKEDEX.get(poke.species_id)
            resultado: str | None = None

            if it.category == "stone":
                step = species.can_evolve_by_stone(it.stone)
                if step is None:
                    await ctx.send(embed=embeds.err_embed(
                        f"**{species.name}** não evolui com **{it.name}**."
                    ))
                    return
                new_species = POKEDEX.get(step.to)
                poke.species_id = new_species.id
                await helpers.update_pokedex(session, user.id, new_species.id, seen=1, caught=1)
                await helpers.take_item(session, user.id, it.key, 1)
                bump_quest(user, "evolve", 1)
                emb = embeds.ok_embed(
                    "✨ Evolução!",
                    f"Usando **{it.name}**, seu **{species.name}** evoluiu para **{new_species.name}**!",
                )
                emb.set_thumbnail(url=settings.sprite(new_species.id, shiny=poke.shiny))
                await ctx.send(embed=emb)
                return

            if it.category == "booster":
                if it.level_amount:
                    before = poke.level
                    poke.level = min(100, poke.level + it.level_amount)
                    resultado = f"**{species.name}** subiu para o nível **{poke.level}** (era {before})."
                elif it.xp_amount:
                    new_level, new_xp, gained = apply_xp(poke.level, poke.xp, it.xp_amount)
                    poke.level, poke.xp = new_level, new_xp
                    resultado = (f"**{species.name}** ganhou **{it.xp_amount} XP**"
                                 + (f" e subiu **{gained}** nível(is)!" if gained else "."))
                await helpers.take_item(session, user.id, it.key, 1)

            if resultado is None:
                await ctx.send(embed=embeds.err_embed("Esse item não pode ser usado assim."))
                return

            # dica de evolução por nível
            evo = species.can_evolve_by_level(poke.level)
            evo_hint = ""
            if evo:
                evo_hint = f"\n💡 **{species.name}** já pode evoluir! Use `{ctx.prefix}evolve {poke.idx}`."
            idx = poke.idx

        await ctx.send(embed=embeds.ok_embed(f"{it.emoji} {it.name} usado!", resultado + evo_hint))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Items(bot))
