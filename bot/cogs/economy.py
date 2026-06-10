"""Economia: saldo, recompensa diária, loja, compra/venda e mercado."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from sqlalchemy import select

from config import settings
from bot.data.items import ITEMS, SHOP_ORDER, find_item, split_item_and_quantity
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import MarketListing, Pokemon, User
from bot.utils import embeds, helpers
from bot.utils.paginator import Paginator, chunk


class Economy(commands.Cog, name="Economia"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------
    @commands.command(name="balance", aliases=["bal", "saldo", "coins"])
    @commands.guild_only()
    async def balance(self, ctx: commands.Context, membro: discord.Member | None = None) -> None:
        """Mostra seu saldo de PokéCoins."""
        alvo = membro or ctx.author
        async with session_scope() as session:
            user = await helpers.fetch_user(session, alvo.id)
            coins = user.coins
            level = user.trainer_level
        emb = embeds.info_text(
            f"💰 **{coins:,}** PokéCoins\n🎖️ Treinador nível **{level}**",
            title=f"Carteira de {alvo.display_name}",
        )
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="daily", aliases=["diario", "diária"])
    @commands.guild_only()
    async def daily(self, ctx: commands.Context) -> None:
        """Resgata a recompensa diária (com bônus de streak)."""
        now = datetime.now(timezone.utc)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            last = user.last_daily
            if last is not None:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if last.date() == now.date():
                    amanha = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
                    restante = amanha - now
                    h, rem = divmod(int(restante.total_seconds()), 3600)
                    m = rem // 60
                    await ctx.send(embed=embeds.err_embed(
                        f"Você já resgatou hoje! Volte em **{h}h {m}min**.",
                        title="Recompensa diária",
                    ))
                    return
                # mantém streak se foi ontem, senão reseta
                if last.date() == (now - timedelta(days=1)).date():
                    user.daily_streak += 1
                else:
                    user.daily_streak = 1
            else:
                user.daily_streak = 1

            bonus = min(user.daily_streak * settings.daily_streak_bonus, settings.daily_streak_max_bonus)
            total = settings.daily_base + bonus
            user.coins += total
            user.last_daily = now
            streak = user.daily_streak

        emb = embeds.ok_embed(
            "Recompensa diária resgatada! 🎁",
            f"Você ganhou **{total:,}** PokéCoins.\n"
            f"🔥 Streak: **{streak}** dia(s) (bônus +{bonus:,})\n"
            f"Volte amanhã para manter o streak!",
        )
        await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    @commands.command(name="shop", aliases=["loja"])
    @commands.guild_only()
    async def shop(self, ctx: commands.Context) -> None:
        """Mostra a loja de itens."""
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            coins = user.coins

        lines = []
        for key in SHOP_ORDER:
            it = ITEMS[key]
            if it.price <= 0:
                continue
            lines.append(
                f"{it.emoji} **{it.name}** — `{it.price:,}` 🪙\n"
                f"   ↳ {it.description}  *(`{ctx.prefix}buy {it.key}`)*"
            )

        pages = []
        for group in chunk(lines, 6):
            emb = discord.Embed(
                title="🏪 Loja PokéMart",
                description="\n".join(group),
                color=settings.color_info,
            )
            emb.set_footer(text=f"Seu saldo: {coins:,} PokéCoins • {ctx.prefix}buy <item> [qtd]")
            pages.append(emb)
        await Paginator(pages, ctx.author.id).start(ctx)

    # ------------------------------------------------------------------
    @commands.command(name="buy", aliases=["comprar"])
    @commands.guild_only()
    async def buy(self, ctx: commands.Context, *, args: str) -> None:
        """Compra um item da loja. Uso: buy <item> [quantidade]. Ex.: `buy Great Ball 3`."""
        item_name, qty = split_item_and_quantity(args)
        quantidade = qty if qty is not None else 1
        it = find_item(item_name)
        if it is None or it.price <= 0:
            await ctx.send(embed=embeds.err_embed(
                f"Item **{item_name}** inválido ou não vendável. Veja a `{ctx.prefix}shop`."))
            return
        if quantidade < 1 or quantidade > 1000:
            await ctx.send(embed=embeds.err_embed("Quantidade inválida (1–1000)."))
            return
        custo = it.price * quantidade
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            if user.coins < custo:
                await ctx.send(embed=embeds.err_embed(
                    f"Saldo insuficiente. Custa **{custo:,}** 🪙, você tem **{user.coins:,}** 🪙."
                ))
                return
            user.coins -= custo
            nova_qtd = await helpers.add_item(session, user.id, it.key, quantidade)
        await ctx.send(embed=embeds.ok_embed(
            "Compra realizada!",
            f"{it.emoji} Você comprou **{quantidade}× {it.name}** por **{custo:,}** 🪙.\n"
            f"Agora você tem **{nova_qtd}** no inventário.",
        ))

    # ------------------------------------------------------------------
    @commands.command(name="sell", aliases=["vender"])
    @commands.guild_only()
    async def sell(self, ctx: commands.Context, *, args: str) -> None:
        """Vende um item de volta por metade do preço. Uso: sell <item> [quantidade]."""
        item_name, qty = split_item_and_quantity(args)
        quantidade = qty if qty is not None else 1
        it = find_item(item_name)
        if it is None:
            await ctx.send(embed=embeds.err_embed("Item inválido. Veja seu inventário com `bag`."))
            return
        if not it.sellable:
            await ctx.send(embed=embeds.err_embed(f"**{it.name}** não pode ser vendido."))
            return
        if quantidade < 1:
            await ctx.send(embed=embeds.err_embed("Quantidade inválida."))
            return
        reembolso = (it.price // 2) * quantidade
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            ok = await helpers.take_item(session, user.id, it.key, quantidade)
            if not ok:
                await ctx.send(embed=embeds.err_embed(f"Você não tem {quantidade}× {it.name}."))
                return
            user.coins += reembolso
        await ctx.send(embed=embeds.ok_embed(
            "Venda realizada!",
            f"Você vendeu **{quantidade}× {it.name}** por **{reembolso:,}** 🪙.",
        ))

    # ==================================================================
    #  MERCADO ENTRE JOGADORES
    # ==================================================================
    @commands.group(name="market", aliases=["mercado", "mk"], invoke_without_command=True)
    @commands.guild_only()
    async def market(self, ctx: commands.Context) -> None:
        """Mercado de pokémon entre jogadores. Subcomandos: add, buy, remove, mine."""
        async with session_scope() as session:
            res = await session.scalars(
                select(MarketListing).where(MarketListing.active == True)  # noqa: E712
                .order_by(MarketListing.price)
            )
            listings = list(res)
            data = []
            for lst in listings:
                poke = await session.get(Pokemon, lst.pokemon_id)
                if poke is None:
                    continue
                sp = POKEDEX.get(poke.species_id)
                data.append((lst, poke, sp))

        if not data:
            await ctx.send(embed=embeds.info_text(
                f"Nenhum pokémon à venda. Anuncie um com `{ctx.prefix}market add <#> <preço>`.",
                title="🛒 Mercado",
            ))
            return

        lines = []
        for lst, poke, sp in data:
            shiny = "✨" if poke.shiny else ""
            lines.append(
                f"`ID {lst.id}` {shiny}**{sp.name}** • Nv {poke.level} • "
                f"IV {poke.iv_percent:.1f}% — **{lst.price:,}** 🪙"
            )

        pages = []
        for group in chunk(lines, 12):
            emb = discord.Embed(
                title="🛒 Mercado",
                description="\n".join(group),
                color=settings.color_info,
            )
            emb.set_footer(text=f"{ctx.prefix}market buy <ID> para comprar")
            pages.append(emb)
        await Paginator(pages, ctx.author.id).start(ctx)

    @market.command(name="add", aliases=["sell", "anunciar"])
    async def market_add(self, ctx: commands.Context, numero: int, preco: int) -> None:
        """Anuncia um pokémon seu no mercado. Uso: market add <#> <preço>."""
        if preco < 1 or preco > 100_000_000:
            await ctx.send(embed=embeds.err_embed("Preço inválido."))
            return
        async with session_scope() as session:
            user = await helpers.fetch_user(session, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, numero)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(f"Você não tem o pokémon #{numero}."))
                return
            if poke.favorite:
                await ctx.send(embed=embeds.err_embed("Não dá para vender um favorito. Use `unfavorite` antes."))
                return
            existing = await session.scalar(
                select(MarketListing).where(
                    MarketListing.pokemon_id == poke.id, MarketListing.active == True  # noqa: E712
                )
            )
            if existing:
                await ctx.send(embed=embeds.err_embed("Esse pokémon já está anunciado."))
                return
            if user.selected_id == poke.id:
                user.selected_id = None
            listing = MarketListing(seller_id=user.id, pokemon_id=poke.id, price=preco)
            session.add(listing)
            await session.flush()
            sp = POKEDEX.get(poke.species_id)
            lid = listing.id
        await ctx.send(embed=embeds.ok_embed(
            "Anúncio criado!",
            f"🛒 **{sp.name}** #{numero} está à venda por **{preco:,}** 🪙 (ID `{lid}`).",
        ))

    @market.command(name="buy", aliases=["comprar"])
    async def market_buy(self, ctx: commands.Context, listing_id: int) -> None:
        """Compra um pokémon anunciado. Uso: market buy <ID>."""
        async with session_scope() as session:
            listing = await session.get(MarketListing, listing_id)
            if listing is None or not listing.active:
                await ctx.send(embed=embeds.err_embed("Anúncio não encontrado ou já vendido."))
                return
            buyer = await helpers.fetch_user(session, ctx.author.id)
            if listing.seller_id == buyer.id:
                await ctx.send(embed=embeds.err_embed("Você não pode comprar seu próprio anúncio. Use `market remove`."))
                return
            if buyer.coins < listing.price:
                await ctx.send(embed=embeds.err_embed(
                    f"Saldo insuficiente. Custa **{listing.price:,}** 🪙."
                ))
                return
            poke = await session.get(Pokemon, listing.pokemon_id)
            if poke is None:
                listing.active = False
                await ctx.send(embed=embeds.err_embed("O pokémon não existe mais."))
                return
            seller = await session.get(User, listing.seller_id)

            # transferência
            buyer.coins -= listing.price
            if seller:
                seller.coins += listing.price
            poke.owner_id = buyer.id
            poke.idx = buyer.next_idx
            buyer.next_idx += 1
            poke.favorite = False
            listing.active = False
            sp = POKEDEX.get(poke.species_id)
            novo_idx = poke.idx
        await ctx.send(embed=embeds.ok_embed(
            "Compra no mercado!",
            f"Você comprou **{sp.name}** por **{listing.price:,}** 🪙. "
            f"Agora é seu pokémon #{novo_idx}.",
        ))

    @market.command(name="remove", aliases=["unlist", "remover", "cancel"])
    async def market_remove(self, ctx: commands.Context, listing_id: int) -> None:
        """Remove um anúncio seu do mercado."""
        async with session_scope() as session:
            listing = await session.get(MarketListing, listing_id)
            user = await helpers.fetch_user(session, ctx.author.id)
            if listing is None or not listing.active or listing.seller_id != user.id:
                await ctx.send(embed=embeds.err_embed("Anúncio não encontrado ou não é seu."))
                return
            listing.active = False
        await ctx.send(embed=embeds.ok_embed("Anúncio removido", "Seu pokémon voltou para a coleção."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Economy(bot))
