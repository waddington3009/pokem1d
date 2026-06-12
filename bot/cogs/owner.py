"""Comandos do DONO do bot (god-mode). Restritos por is_owner() porque a
economia é global — qualquer admin de servidor não deve poder dar moedas/pokémon.
"""
from __future__ import annotations

import discord
from discord.ext import commands

from bot.data.items import find_item, split_item_and_quantity
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.utils import embeds, helpers


class Owner(commands.Cog, name="Dono"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_check(self, ctx: commands.Context) -> bool:
        # todo comando aqui exige ser dono do bot
        if not await self.bot.is_owner(ctx.author):
            raise commands.NotOwner()
        return True

    async def cog_before_invoke(self, ctx: commands.Context) -> None:
        # apaga a mensagem do comando de admin (não polui o chat / esconde o que foi dado)
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

    # ------------------------------------------------------------------
    @commands.command(name="addpokemon", aliases=["givepokemon", "darpokemon"])
    @commands.guild_only()
    async def addpokemon(self, ctx: commands.Context, *, args: str) -> None:
        """[Dono] Dá um pokémon a alguém. Uso: addpokemon <nome> <nível> <@usuário>."""
        parts = args.rsplit(None, 2)  # separa os 2 últimos: <nível> <@usuário>
        if len(parts) < 3:
            await ctx.send(embed=embeds.err_embed(
                "Uso: `addpokemon <nome> <nível> <@usuário>`\nEx.: `addpokemon Greninja 50 @fulano`"))
            return
        name, level_str, user_str = parts
        if not level_str.isdigit():
            await ctx.send(embed=embeds.err_embed("Nível inválido. Ex.: `addpokemon Greninja 50 @fulano`"))
            return
        level = max(1, min(100, int(level_str)))
        species = POKEDEX.by_name(name)
        if species is None:
            await ctx.send(embed=embeds.err_embed(f"Espécie **{name}** não encontrada."))
            return
        try:
            member = await commands.MemberConverter().convert(ctx, user_str)
        except commands.BadArgument:
            await ctx.send(embed=embeds.err_embed(f"Usuário **{user_str}** não encontrado."))
            return

        async with session_scope() as session:
            user = await helpers.fetch_user(session, member.id)
            poke = await helpers.create_pokemon(session, user, species, level=level)
            await helpers.update_pokedex(session, user.id, species.id, seen=1, caught=1)
            idx = poke.idx
        await ctx.send(embed=embeds.ok_embed(
            "Pokémon concedido 🎁",
            f"**{species.name}** (Nv {level}) foi dado para {member.mention} — pokémon #{idx}."))

    # ------------------------------------------------------------------
    @commands.command(name="addcoins", aliases=["addmoney", "darmoedas"])
    @commands.guild_only()
    async def addcoins(self, ctx: commands.Context, membro: discord.Member, quantidade: int) -> None:
        """[Dono] Adiciona moedas a alguém. Uso: addcoins <@usuário> <quantia>."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, membro.id)
            user.coins = max(0, user.coins + quantidade)
            novo = user.coins
        await ctx.send(embed=embeds.ok_embed(
            "Moedas adicionadas 💰",
            f"{'+' if quantidade >= 0 else ''}{quantidade:,} para {membro.mention}. Saldo: **{novo:,}**."))

    @commands.command(name="setcoins", aliases=["setmoney"])
    @commands.guild_only()
    async def setcoins(self, ctx: commands.Context, membro: discord.Member, quantidade: int) -> None:
        """[Dono] Define o saldo de alguém. Uso: setcoins <@usuário> <quantia>."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, membro.id)
            user.coins = max(0, quantidade)
            novo = user.coins
        await ctx.send(embed=embeds.ok_embed(
            "Saldo definido 💰", f"Saldo de {membro.mention} agora é **{novo:,}**."))

    @commands.command(name="removecoins", aliases=["remcoins", "tirarmoedas"])
    @commands.guild_only()
    async def removecoins(self, ctx: commands.Context, membro: discord.Member, quantidade: int) -> None:
        """[Dono] Remove moedas de alguém. Uso: removecoins <@usuário> <quantia>."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, membro.id)
            user.coins = max(0, user.coins - abs(quantidade))
            novo = user.coins
        await ctx.send(embed=embeds.ok_embed(
            "Moedas removidas 💸", f"Saldo de {membro.mention} agora é **{novo:,}**."))

    # ------------------------------------------------------------------
    @commands.command(name="additem", aliases=["giveitem", "daritem"])
    @commands.guild_only()
    async def additem(self, ctx: commands.Context, membro: discord.Member, *, args: str) -> None:
        """[Dono] Dá um item a alguém. Uso: additem <@usuário> <item> [qtd]."""
        item_name, qty = split_item_and_quantity(args)
        quantidade = qty if qty is not None else 1
        it = find_item(item_name)
        if it is None:
            await ctx.send(embed=embeds.err_embed(f"Item **{item_name}** não encontrado."))
            return
        async with session_scope() as session:
            user = await helpers.fetch_user(session, membro.id)
            nova = await helpers.add_item(session, user.id, it.key, quantidade)
        await ctx.send(embed=embeds.ok_embed(
            "Item concedido 🎁",
            f"{it.emoji} **{quantidade}× {it.name}** para {membro.mention} (agora tem {nova})."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Owner(bot))
