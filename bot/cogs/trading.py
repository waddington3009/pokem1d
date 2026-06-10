"""Sistema de trocas com dupla confirmação (anti-scam)."""
from __future__ import annotations

from dataclasses import dataclass, field

import discord
from discord.ext import commands
from sqlalchemy import select

from config import settings
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import MarketListing, Pokemon
from bot.utils import embeds, helpers


@dataclass
class TradeSide:
    user_id: int                       # discord id
    pokemon_idxs: set[int] = field(default_factory=set)
    coins: int = 0
    confirmed: bool = False


@dataclass
class TradeSession:
    a: TradeSide
    b: TradeSide
    channel_id: int

    def side(self, discord_id: int) -> TradeSide | None:
        if self.a.user_id == discord_id:
            return self.a
        if self.b.user_id == discord_id:
            return self.b
        return None

    def reset_confirmations(self) -> None:
        self.a.confirmed = False
        self.b.confirmed = False


class Trading(commands.Cog, name="Trocas"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # cada participante (discord_id) -> sua sessão de troca
        self.sessions: dict[int, TradeSession] = {}

    def _session_of(self, discord_id: int) -> TradeSession | None:
        return self.sessions.get(discord_id)

    async def _state_embed(self, ctx, session: TradeSession) -> discord.Embed:
        emb = discord.Embed(title="🤝 Troca em andamento", color=settings.color_info)
        for side in (session.a, session.b):
            member = ctx.guild.get_member(side.user_id)
            name = member.display_name if member else str(side.user_id)
            check = "✅" if side.confirmed else "⏳"
            lines = []
            if side.pokemon_idxs:
                async with session_scope() as db:
                    user = await helpers.fetch_user(db, side.user_id)
                    for idx in sorted(side.pokemon_idxs):
                        poke = await helpers.get_pokemon_by_idx(db, user.id, idx)
                        if poke:
                            sp = POKEDEX.get(poke.species_id)
                            shiny = "✨" if poke.shiny else ""
                            lines.append(f"`#{idx}` {shiny}{sp.name} Nv{poke.level}")
            if side.coins:
                lines.append(f"💰 {side.coins:,} PokéCoins")
            value = "\n".join(lines) if lines else "*(nada ainda)*"
            emb.add_field(name=f"{check} {name}", value=value, inline=True)
        emb.set_footer(text=f"{ctx.prefix}trade add <#> • coins <n> • confirm • cancel")
        return emb

    # ------------------------------------------------------------------
    @commands.group(name="trade", aliases=["troca", "trocar"], invoke_without_command=True)
    @commands.guild_only()
    async def trade(self, ctx: commands.Context, membro: discord.Member | None = None) -> None:
        """Inicia uma troca com @usuário, ou mostra a troca atual."""
        existing = self._session_of(ctx.author.id)
        if membro is None:
            if existing:
                await ctx.send(embed=await self._state_embed(ctx, existing))
            else:
                await ctx.send(embed=embeds.info_text(
                    f"Use `{ctx.prefix}trade @usuário` para iniciar uma troca.",
                    title="🤝 Trocas",
                ))
            return

        if membro.bot or membro.id == ctx.author.id:
            await ctx.send(embed=embeds.err_embed("Escolha outro jogador válido para trocar."))
            return
        if existing:
            await ctx.send(embed=embeds.err_embed("Você já está em uma troca. Use `trade cancel` antes."))
            return
        if self._session_of(membro.id):
            await ctx.send(embed=embeds.err_embed(f"{membro.display_name} já está em outra troca."))
            return

        session = TradeSession(
            a=TradeSide(ctx.author.id), b=TradeSide(membro.id), channel_id=ctx.channel.id
        )
        self.sessions[ctx.author.id] = session
        self.sessions[membro.id] = session
        await ctx.send(embed=embeds.ok_embed(
            "Troca iniciada!",
            f"{ctx.author.mention} ⇄ {membro.mention}\n"
            f"Adicionem itens com `{ctx.prefix}trade add <#>` e confirmem com `{ctx.prefix}trade confirm`.",
        ))

    @trade.command(name="add", aliases=["adicionar"])
    async def trade_add(self, ctx: commands.Context, numero: int) -> None:
        """Adiciona um pokémon seu à oferta."""
        session = self._session_of(ctx.author.id)
        if session is None:
            await ctx.send(embed=embeds.err_embed("Você não está em uma troca."))
            return
        async with session_scope() as db:
            user = await helpers.fetch_user(db, ctx.author.id)
            poke = await helpers.get_pokemon_by_idx(db, user.id, numero)
            if poke is None:
                await ctx.send(embed=embeds.err_embed(f"Você não tem o pokémon #{numero}."))
                return
            if poke.favorite:
                await ctx.send(embed=embeds.err_embed("Favoritos não podem ser trocados. Use `unfavorite`."))
                return
        side = session.side(ctx.author.id)
        side.pokemon_idxs.add(numero)
        session.reset_confirmations()
        await ctx.send(embed=await self._state_embed(ctx, session))

    @trade.command(name="remove", aliases=["remover", "rem"])
    async def trade_remove(self, ctx: commands.Context, numero: int) -> None:
        """Remove um pokémon da sua oferta."""
        session = self._session_of(ctx.author.id)
        if session is None:
            await ctx.send(embed=embeds.err_embed("Você não está em uma troca."))
            return
        side = session.side(ctx.author.id)
        side.pokemon_idxs.discard(numero)
        session.reset_confirmations()
        await ctx.send(embed=await self._state_embed(ctx, session))

    @trade.command(name="coins", aliases=["moedas", "dinheiro"])
    async def trade_coins(self, ctx: commands.Context, quantidade: int) -> None:
        """Adiciona PokéCoins à sua oferta (0 para remover)."""
        session = self._session_of(ctx.author.id)
        if session is None:
            await ctx.send(embed=embeds.err_embed("Você não está em uma troca."))
            return
        if quantidade < 0:
            await ctx.send(embed=embeds.err_embed("Quantidade inválida."))
            return
        async with session_scope() as db:
            user = await helpers.fetch_user(db, ctx.author.id)
            if user.coins < quantidade:
                await ctx.send(embed=embeds.err_embed(f"Você só tem {user.coins:,} PokéCoins."))
                return
        session.side(ctx.author.id).coins = quantidade
        session.reset_confirmations()
        await ctx.send(embed=await self._state_embed(ctx, session))

    @trade.command(name="cancel", aliases=["cancelar"])
    async def trade_cancel(self, ctx: commands.Context) -> None:
        """Cancela a troca atual."""
        session = self._session_of(ctx.author.id)
        if session is None:
            await ctx.send(embed=embeds.err_embed("Você não está em uma troca."))
            return
        self.sessions.pop(session.a.user_id, None)
        self.sessions.pop(session.b.user_id, None)
        await ctx.send(embed=embeds.info_text("Troca cancelada. ❌"))

    @trade.command(name="confirm", aliases=["confirmar", "ok"])
    async def trade_confirm(self, ctx: commands.Context) -> None:
        """Confirma sua parte. A troca só ocorre quando ambos confirmam."""
        session = self._session_of(ctx.author.id)
        if session is None:
            await ctx.send(embed=embeds.err_embed("Você não está em uma troca."))
            return
        side = session.side(ctx.author.id)
        if not side.pokemon_idxs and not side.coins and not session.side(
            session.b.user_id if side is session.a else session.a.user_id
        ).pokemon_idxs:
            pass  # permite troca vazia? melhor exigir algo de um lado — segue.
        side.confirmed = True

        if not (session.a.confirmed and session.b.confirmed):
            await ctx.send(embed=embeds.ok_embed(
                "Confirmado!",
                f"{ctx.author.display_name} confirmou. Aguardando o outro jogador...",
            ))
            await ctx.send(embed=await self._state_embed(ctx, session))
            return

        # ambos confirmaram — executa a troca
        ok, msg = await self._execute(session)
        self.sessions.pop(session.a.user_id, None)
        self.sessions.pop(session.b.user_id, None)
        if ok:
            await ctx.send(embed=embeds.ok_embed("✅ Troca concluída!", msg))
        else:
            await ctx.send(embed=embeds.err_embed(msg, title="Troca falhou"))

    async def _execute(self, session: TradeSession) -> tuple[bool, str]:
        """Valida e efetiva a troca dentro de uma transação."""
        async with session_scope() as db:
            user_a = await helpers.fetch_user(db, session.a.user_id)
            user_b = await helpers.fetch_user(db, session.b.user_id)

            # valida moedas
            if user_a.coins < session.a.coins or user_b.coins < session.b.coins:
                return False, "Um dos jogadores não tem moedas suficientes."

            # coleta os pokémon de cada lado e valida posse
            async def collect(user, idxs) -> list[Pokemon] | None:
                out = []
                for idx in idxs:
                    poke = await helpers.get_pokemon_by_idx(db, user.id, idx)
                    if poke is None or poke.favorite:
                        return None
                    out.append(poke)
                return out

            pokes_a = await collect(user_a, session.a.pokemon_idxs)
            pokes_b = await collect(user_b, session.b.pokemon_idxs)
            if pokes_a is None or pokes_b is None:
                return False, "Um dos pokémon não está mais disponível para troca."

            # remove anúncios de mercado eventuais
            async def unlist(pokes):
                for poke in pokes:
                    listing = await db.scalar(
                        select(MarketListing).where(
                            MarketListing.pokemon_id == poke.id,
                            MarketListing.active == True,  # noqa: E712
                        )
                    )
                    if listing:
                        listing.active = False

            await unlist(pokes_a)
            await unlist(pokes_b)

            # transfere moedas
            user_a.coins += session.b.coins - session.a.coins
            user_b.coins += session.a.coins - session.b.coins

            # transfere pokémon A -> B
            for poke in pokes_a:
                if user_a.selected_id == poke.id:
                    user_a.selected_id = None
                poke.owner_id = user_b.id
                poke.idx = user_b.next_idx
                user_b.next_idx += 1
            # transfere pokémon B -> A
            for poke in pokes_b:
                if user_b.selected_id == poke.id:
                    user_b.selected_id = None
                poke.owner_id = user_a.id
                poke.idx = user_a.next_idx
                user_a.next_idx += 1

        resumo = (
            f"<@{session.a.user_id}> enviou {len(session.a.pokemon_idxs)} pokémon "
            f"+ {session.a.coins:,} 🪙\n"
            f"<@{session.b.user_id}> enviou {len(session.b.pokemon_idxs)} pokémon "
            f"+ {session.b.coins:,} 🪙"
        )
        return True, resumo


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Trading(bot))
