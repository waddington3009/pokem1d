"""Comandos gerais: início, ping, info do bot e consulta de espécies."""
from __future__ import annotations

import time

import discord
from discord.ext import commands

from config import settings
from bot.data.pokemon_data import POKEDEX
from bot.data.types import TYPE_EMOJI, type_color
from bot.database.db import session_scope
from bot.utils import embeds, helpers
from bot.utils.rarity import RARITY_EMOJI, rarity_label


class General(commands.Cog, name="Geral"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    @commands.command(name="start", aliases=["comecar", "começar", "iniciar"])
    @commands.guild_only()
    async def start(self, ctx: commands.Context) -> None:
        """Começa sua jornada: ganhe um pokémon inicial e itens."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            count = await helpers.pokemon_count(session, user.id)
            if count > 0:
                await ctx.send(embed=embeds.err_embed(
                    "Você já começou sua jornada! Use `pokemon` para ver sua coleção."
                ))
                return
            starter = POKEDEX.random_starter()
            poke = await helpers.create_pokemon(session, user, starter, level=5)
            await helpers.update_pokedex(session, user.id, starter.id, seen=1, caught=1)
            user.total_caught += 1
            user.coins += 500
            await helpers.add_item(session, user.id, "pokeball", 10)
            await helpers.add_item(session, user.id, "greatball", 5)

        emb = embeds.ok_embed(
            "🎉 Bem-vindo ao mundo Pokémon!",
            f"Você recebeu seu inicial: **{starter.name}** (Nv 5)!\n\n"
            f"🎁 Bônus inicial: **500 PokéCoins**, 10× Poké Ball e 5× Great Ball.\n\n"
            f"**Próximos passos:**\n"
            f"• Converse no servidor para fazer pokémon aparecerem\n"
            f"• Capture com `{ctx.prefix}catch <nome>`\n"
            f"• Veja sua coleção com `{ctx.prefix}pokemon`\n"
            f"• Resgate moedas com `{ctx.prefix}daily`\n"
            f"• Veja tudo em `{ctx.prefix}help`",
        )
        emb.set_thumbnail(url=settings.sprite(starter.id))
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        """Mostra a latência do bot."""
        start = time.perf_counter()
        msg = await ctx.send("🏓 Pong...")
        elapsed = (time.perf_counter() - start) * 1000
        await msg.edit(content=(
            f"🏓 **Pong!**\nWebSocket: `{self.bot.latency * 1000:.0f}ms` • "
            f"Mensagem: `{elapsed:.0f}ms`"
        ))

    # ------------------------------------------------------------------
    @commands.command(name="botinfo", aliases=["about", "sobre", "info-bot"])
    async def botinfo(self, ctx: commands.Context) -> None:
        """Informações e estatísticas do bot."""
        from bot import __version__
        emb = discord.Embed(
            title="🤖 PokeM1D",
            description="Bot de mini-game Pokémon: capture, evolua, batalhe e troque!",
            color=settings.color_default,
        )
        emb.add_field(name="Servidores", value=str(len(self.bot.guilds)), inline=True)
        emb.add_field(name="Espécies", value=str(POKEDEX.count()), inline=True)
        emb.add_field(name="Latência", value=f"{self.bot.latency * 1000:.0f}ms", inline=True)
        emb.add_field(name="Versão", value=__version__, inline=True)
        emb.add_field(name="Biblioteca", value=f"discord.py {discord.__version__}", inline=True)
        emb.set_footer(text=f"Use {ctx.prefix}help para a lista de comandos.")
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="species", aliases=["dexinfo", "especie", "espécie", "lookup"])
    async def species(self, ctx: commands.Context, *, nome: str) -> None:
        """Consulta os dados de uma espécie na Pokédex global. Uso: species <nome>."""
        sp = POKEDEX.by_name(nome)
        if sp is None:
            await ctx.send(embed=embeds.err_embed(f"Espécie `{nome}` não encontrada."))
            return

        emb = discord.Embed(
            title=f"#{sp.id:03d} — {sp.name}",
            color=type_color(sp.types),
        )
        emb.set_image(url=settings.sprite(sp.id, official=True))
        emb.add_field(
            name="Tipo",
            value=" ".join(f"{TYPE_EMOJI.get(t,'')} {t.title()}" for t in sp.types),
            inline=True,
        )
        emb.add_field(
            name="Raridade",
            value=f"{RARITY_EMOJI.get(sp.rarity,'')} {rarity_label(sp.rarity)}",
            inline=True,
        )
        emb.add_field(name="Total base", value=str(sp.base_total), inline=True)

        stat_labels = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}
        stat_lines = "\n".join(
            f"`{stat_labels[k]:<3}` {v:>3} {'▰' * (v // 10)}"
            for k, v in sp.base_stats.items()
        )
        emb.add_field(name="Atributos base", value=stat_lines, inline=False)

        if sp.evolutions:
            evos = []
            for e in sp.evolutions:
                target = POKEDEX.get(e.to)
                tname = target.name if target else f"#{e.to}"
                if e.method == "level":
                    evos.append(f"➜ **{tname}** (nível {e.level})")
                elif e.method == "stone":
                    evos.append(f"➜ **{tname}** ({e.stone}-stone)")
                else:
                    evos.append(f"➜ **{tname}** ({e.method})")
            emb.add_field(name="Evolução", value="\n".join(evos), inline=False)

        emb.add_field(
            name="Golpes",
            value=", ".join(m.replace("-", " ").title() for m in sp.moves),
            inline=False,
        )
        await ctx.send(embed=emb)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(General(bot))
