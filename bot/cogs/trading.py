"""Sistema de trocas com painel de botões e dupla confirmação (anti-scam).

`/trade @usuário` abre um painel PÚBLICO no canal com botões: cada jogador
adiciona pokémon (menu próprio, efêmero), adiciona moedas (modal), confirma e
cancela. A troca só ocorre quando AMBOS confirmam; qualquer mudança na oferta
zera as confirmações.
"""
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

PER_PAGE = 25


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
    view: "TradeView | None" = None

    def side(self, discord_id: int) -> TradeSide | None:
        if self.a.user_id == discord_id:
            return self.a
        if self.b.user_id == discord_id:
            return self.b
        return None

    def reset_confirmations(self) -> None:
        self.a.confirmed = False
        self.b.confirmed = False


# ==========================================================================
class Trading(commands.Cog, name="Trocas"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # cada participante (discord_id) -> sua sessão de troca
        self.sessions: dict[int, TradeSession] = {}

    def _session_of(self, discord_id: int) -> TradeSession | None:
        return self.sessions.get(discord_id)

    def _end_session(self, session: TradeSession) -> None:
        self.sessions.pop(session.a.user_id, None)
        self.sessions.pop(session.b.user_id, None)

    # ------------------------------------------------------------------
    @commands.hybrid_command(name="trade", aliases=["troca", "trocar"])
    @commands.guild_only()
    async def trade(self, ctx: commands.Context, membro: discord.Member | None = None) -> None:
        """Abre um painel de troca com @usuário (botões: pokémon, moedas, confirmar)."""
        existing = self._session_of(ctx.author.id)
        if membro is None:
            msg = ("Use **`/trade @usuário`** para abrir uma troca."
                   if existing is None else
                   "Você já está em uma troca — use o painel aberto no canal.")
            await self._reply(ctx, embeds.info_text(msg, title="🤝 Trocas"))
            return
        if membro.bot or membro.id == ctx.author.id:
            await self._reply(ctx, embeds.err_embed("Escolha outro jogador válido para trocar."))
            return
        if existing:
            await self._reply(ctx, embeds.err_embed("Você já está em uma troca. Cancele a atual antes."))
            return
        if self._session_of(membro.id):
            await self._reply(ctx, embeds.err_embed(f"{membro.display_name} já está em outra troca."))
            return

        session = TradeSession(a=TradeSide(ctx.author.id), b=TradeSide(membro.id),
                               channel_id=ctx.channel.id)
        self.sessions[ctx.author.id] = session
        self.sessions[membro.id] = session
        view = TradeView(self, session)
        session.view = view
        emb = await self.state_embed(ctx.guild, session)
        # mensagem PÚBLICA no canal (os dois clicam nos botões)
        if ctx.interaction is not None:
            await ctx.interaction.response.send_message(
                content=f"{ctx.author.mention} ⇄ {membro.mention}", embed=emb, view=view)
            view.message = await ctx.interaction.original_response()
        else:
            view.message = await ctx.send(
                content=f"{ctx.author.mention} ⇄ {membro.mention}", embed=emb, view=view)

    async def _reply(self, ctx: commands.Context, emb: discord.Embed) -> None:
        if ctx.interaction is not None:
            await ctx.interaction.response.send_message(embed=emb, ephemeral=True)
        else:
            await ctx.send(embed=emb)

    # ------------------------------------------------------------------
    async def state_embed(self, guild: discord.Guild, session: TradeSession) -> discord.Embed:
        emb = discord.Embed(title="🤝 Troca em andamento", color=settings.color_info)
        for side in (session.a, session.b):
            member = guild.get_member(side.user_id)
            name = member.display_name if member else str(side.user_id)
            check = "✅ pronto" if side.confirmed else "⏳ ajustando"
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
            emb.add_field(name=f"{check} · {name}", value=value, inline=True)
        emb.set_footer(text="➕ pokémon · 💰 moedas · ✅ confirmar (os dois) · ❌ cancelar")
        return emb

    async def execute(self, session: TradeSession) -> tuple[bool, str]:
        """Valida e efetiva a troca dentro de uma transação."""
        async with session_scope() as db:
            user_a = await helpers.fetch_user(db, session.a.user_id)
            user_b = await helpers.fetch_user(db, session.b.user_id)

            if user_a.coins < session.a.coins or user_b.coins < session.b.coins:
                return False, "Um dos jogadores não tem moedas suficientes."

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

            async def unlist(pokes):
                for poke in pokes:
                    listing = await db.scalar(select(MarketListing).where(
                        MarketListing.pokemon_id == poke.id,
                        MarketListing.active == True))  # noqa: E712
                    if listing:
                        listing.active = False

            await unlist(pokes_a)
            await unlist(pokes_b)

            # transfere moedas
            user_a.coins += session.b.coins - session.a.coins
            user_b.coins += session.a.coins - session.b.coins

            for poke in pokes_a:
                if user_a.selected_id == poke.id:
                    user_a.selected_id = None
                user_a.party = [p for p in (user_a.party or []) if p != poke.idx]
                poke.owner_id = user_b.id
                poke.idx = user_b.next_idx
                user_b.next_idx += 1
            for poke in pokes_b:
                if user_b.selected_id == poke.id:
                    user_b.selected_id = None
                user_b.party = [p for p in (user_b.party or []) if p != poke.idx]
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


# ==========================================================================
#  Painel principal (mensagem pública, os dois jogadores usam)
# ==========================================================================
class TradeView(discord.ui.View):
    def __init__(self, cog: Trading, session: TradeSession):
        super().__init__(timeout=300)
        self.cog = cog
        self.session = session
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if self.session.side(interaction.user.id) is None:
            await interaction.response.send_message("Essa troca não é sua. 😉", ephemeral=True)
            return False
        return True

    async def refresh(self, interaction: discord.Interaction | None = None) -> None:
        emb = await self.cog.state_embed(self.message.guild, self.session)
        if interaction is not None and not interaction.response.is_done():
            await interaction.response.edit_message(embed=emb, view=self)
        elif self.message is not None:
            await self.message.edit(embed=emb, view=self)

    async def on_timeout(self) -> None:
        self.cog._end_session(self.session)
        for c in self.children:
            c.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(content="⏳ Troca expirada.", view=self)
            except discord.HTTPException:
                pass

    # ---- botões ----
    @discord.ui.button(label="Adicionar Pokémon", emoji="➕", style=discord.ButtonStyle.success)
    async def add_poke(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        view = await AddPickerView.create(self, interaction.user.id)
        if not view.has_options:
            await interaction.response.send_message(
                "Você não tem pokémon disponíveis para trocar (favoritos não contam).", ephemeral=True)
            return
        await interaction.response.send_message(
            "Escolha um pokémon para **adicionar** à sua oferta:", view=view, ephemeral=True)

    @discord.ui.button(label="Remover Pokémon", emoji="➖", style=discord.ButtonStyle.secondary)
    async def remove_poke(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        side = self.session.side(interaction.user.id)
        if not side.pokemon_idxs:
            await interaction.response.send_message("Você não ofereceu nenhum pokémon ainda.", ephemeral=True)
            return
        view = await RemovePickerView.create(self, interaction.user.id)
        await interaction.response.send_message(
            "Escolha um pokémon para **remover** da sua oferta:", view=view, ephemeral=True)

    @discord.ui.button(label="Moedas", emoji="💰", style=discord.ButtonStyle.secondary)
    async def coins(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.send_modal(CoinsModal(self, interaction.user.id))

    @discord.ui.button(label="Confirmar", emoji="✅", style=discord.ButtonStyle.primary)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        side = self.session.side(interaction.user.id)
        if not (self.session.a.pokemon_idxs or self.session.a.coins or
                self.session.b.pokemon_idxs or self.session.b.coins):
            await interaction.response.send_message(
                "A troca está vazia — adicione pokémon ou moedas primeiro.", ephemeral=True)
            return
        side.confirmed = True
        if not (self.session.a.confirmed and self.session.b.confirmed):
            return await self.refresh(interaction)
        # ambos confirmaram — executa
        ok, msg = await self.cog.execute(self.session)
        self.cog._end_session(self.session)
        for c in self.children:
            c.disabled = True
        self.stop()
        emb = (embeds.ok_embed("✅ Troca concluída!", msg) if ok
               else embeds.err_embed(msg, title="Troca falhou"))
        await interaction.response.edit_message(content=None, embed=emb, view=self)

    @discord.ui.button(label="Cancelar", emoji="❌", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.cog._end_session(self.session)
        for c in self.children:
            c.disabled = True
        self.stop()
        await interaction.response.edit_message(
            content=None, embed=embeds.info_text("Troca cancelada. ❌", title="🤝 Trocas"), view=self)


# ==========================================================================
#  Sub-painéis efêmeros (cada jogador escolhe os SEUS pokémon)
# ==========================================================================
class AddPickerView(discord.ui.View):
    def __init__(self, parent: TradeView, user_id: int):
        super().__init__(timeout=120)
        self.parent = parent
        self.user_id = user_id
        self.page = 0
        self.has_options = False

    @classmethod
    async def create(cls, parent: TradeView, user_id: int) -> "AddPickerView":
        self = cls(parent, user_id)
        await self._build()
        return self

    async def _eligible(self) -> list[tuple[int, str, str]]:
        side = self.parent.session.side(self.user_id)
        async with session_scope() as db:
            user = await helpers.fetch_user(db, self.user_id)
            mons = await helpers.list_pokemon(db, user.id)
        out = []
        for m in mons:
            if m.favorite or m.idx in side.pokemon_idxs:
                continue
            sp = POKEDEX.get(m.species_id)
            if sp:
                out.append((m.idx, f"#{m.idx} {sp.name}", f"Nv {m.level} · IV {m.iv_percent:.0f}%"))
        return out

    async def _build(self) -> None:
        self.clear_items()
        elig = await self._eligible()
        self.has_options = bool(elig)
        if not elig:
            return
        pages = max(1, (len(elig) + PER_PAGE - 1) // PER_PAGE)
        self.page %= pages
        sl = elig[self.page * PER_PAGE:(self.page + 1) * PER_PAGE]
        opts = [discord.SelectOption(label=lbl[:100], description=desc[:100], value=str(idx))
                for idx, lbl, desc in sl]
        self.add_item(_AddSelect(self, opts, pages))
        if pages > 1:
            self.add_item(_PageBtn(self, -1, "◀️"))
            self.add_item(_PageBtn(self, +1, "▶️"))


class _AddSelect(discord.ui.Select):
    def __init__(self, view: AddPickerView, opts, pages: int):
        super().__init__(placeholder=f"Seus pokémon (pág {view.page + 1}/{pages})", options=opts)
        self._picker = view

    async def callback(self, interaction: discord.Interaction) -> None:
        idx = int(self.values[0])
        session = self._picker.parent.session
        side = session.side(self._picker.user_id)
        side.pokemon_idxs.add(idx)
        session.reset_confirmations()
        await self._picker.parent.refresh()           # atualiza o painel público
        await interaction.response.edit_message(       # fecha o efêmero
            content=f"✅ Pokémon `#{idx}` adicionado à sua oferta.", view=None)


class _PageBtn(discord.ui.Button):
    def __init__(self, view: AddPickerView, delta: int, emoji: str):
        super().__init__(emoji=emoji, style=discord.ButtonStyle.secondary)
        self._picker, self._d = view, delta

    async def callback(self, interaction: discord.Interaction) -> None:
        self._picker.page += self._d
        await self._picker._build()
        await interaction.response.edit_message(view=self._picker)


class RemovePickerView(discord.ui.View):
    def __init__(self, parent: TradeView, user_id: int):
        super().__init__(timeout=120)
        self.parent = parent
        self.user_id = user_id

    @classmethod
    async def create(cls, parent: TradeView, user_id: int) -> "RemovePickerView":
        self = cls(parent, user_id)
        side = parent.session.side(user_id)
        opts = []
        async with session_scope() as db:
            user = await helpers.fetch_user(db, user_id)
            for idx in sorted(side.pokemon_idxs):
                poke = await helpers.get_pokemon_by_idx(db, user.id, idx)
                if poke:
                    sp = POKEDEX.get(poke.species_id)
                    opts.append(discord.SelectOption(
                        label=f"#{idx} {sp.name}"[:100],
                        description=f"Nv {poke.level} · IV {poke.iv_percent:.0f}%", value=str(idx)))
        if opts:
            self.add_item(_RemoveSelect(self, opts))
        return self


class _RemoveSelect(discord.ui.Select):
    def __init__(self, view: RemovePickerView, opts):
        super().__init__(placeholder="Pokémon da sua oferta", options=opts)
        self._picker = view

    async def callback(self, interaction: discord.Interaction) -> None:
        idx = int(self.values[0])
        session = self._picker.parent.session
        session.side(self._picker.user_id).pokemon_idxs.discard(idx)
        session.reset_confirmations()
        await self._picker.parent.refresh()
        await interaction.response.edit_message(
            content=f"➖ Pokémon `#{idx}` removido da sua oferta.", view=None)


class CoinsModal(discord.ui.Modal, title="💰 Moedas na troca"):
    valor = discord.ui.TextInput(label="Quantas PokéCoins oferecer?",
                                 placeholder="Ex.: 5000 (0 para remover)", min_length=1, max_length=12)

    def __init__(self, parent: TradeView, user_id: int):
        super().__init__()
        self.parent = parent
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.valor.value).strip().replace(".", "").replace(",", "")
        if not raw.isdigit():
            await interaction.response.send_message("Valor inválido (use só números).", ephemeral=True)
            return
        qty = int(raw)
        async with session_scope() as db:
            user = await helpers.fetch_user(db, self.user_id)
            if user.coins < qty:
                await interaction.response.send_message(
                    f"Você só tem {user.coins:,} PokéCoins.", ephemeral=True)
                return
        session = self.parent.session
        session.side(self.user_id).coins = qty
        session.reset_confirmations()
        await self.parent.refresh()
        await interaction.response.send_message(
            f"💰 Sua oferta de moedas agora é **{qty:,}**.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Trading(bot))
