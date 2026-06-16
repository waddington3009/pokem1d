"""Hub central (p!menu / /menu): painel com botões que se edita no lugar.

Aberto por slash (`/menu`) = resposta **ephemeral** (só o jogador vê) ou por
prefixo (`p!menu`) = público. O estado mora no banco; o hub é a janela.

Telas: Home · Perfil · Time (gerir) · Coleção→detalhe (selecionar/favoritar/
evoluir/soltar) · Loja (comprar) · Market (comprar) · Missões · Liga · Explorar
(encontro com capturar/batalhar/ignorar na própria caixa).
"""
from __future__ import annotations

import random
import time
from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from sqlalchemy import func, select

from config import settings
from bot.data.gyms import CHALLENGES, CHALLENGES_BY_KEY, party_slots
from bot.data.items import ITEMS, SHOP_ORDER, find_item, get_item
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import MarketListing, PokedexEntry, Pokemon, User
from bot.utils import embeds, helpers
from bot.utils.images import render_grid
from bot.utils.progression import ACHIEVEMENTS, claim_quest, quest_state
from bot.utils.rarity import RARITY_EMOJI, pick_spawn_species, rarity_label, roll_shiny
from bot.utils.team_scene import render_team

PER_PAGE_DEX = 9
PER_PAGE_SHOP = 6
PER_PAGE_MARKET = 10


def _claim_daily(user) -> tuple[bool, str]:
    now = datetime.now(timezone.utc)
    last = user.last_daily
    if last is not None:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last.date() == now.date():
            amanha = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            h, rem = divmod(int((amanha - now).total_seconds()), 3600)
            return False, f"⏳ Você já resgatou hoje. Volte em **{h}h {rem // 60}min**."
        user.daily_streak = (user.daily_streak + 1) if last.date() == (now - timedelta(days=1)).date() else 1
    else:
        user.daily_streak = 1
    bonus = min(user.daily_streak * settings.daily_streak_bonus, settings.daily_streak_max_bonus)
    total = settings.daily_base + bonus
    user.coins += total
    user.last_daily = now
    return True, f"🎁 +**{total:,}** PokéCoins! 🔥 Streak: **{user.daily_streak}** (bônus +{bonus:,})."


# ==========================================================================
class HubView(discord.ui.View):
    def __init__(self, ctx: commands.Context):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.author_id = ctx.author.id
        self.prefix = ctx.prefix
        self.screen = "home"
        self.page = 0
        self.flash = ""
        self.message: discord.Message | None = None
        # estado de telas específicas
        self.detail_idx: int | None = None
        self.shop_key: str | None = None
        self.market_id: int | None = None
        self.select_mode: str | None = None       # add | remove | lead
        self.encounter: dict | None = None         # {species, shiny, level, location, phase}
        self.result: tuple | None = None           # ('nothing'|'coins'|'caught'|'fled'|'battle', dados)
        self.last_explore = 0.0
        # dados em cache para montar selects (preenchidos no render)
        self._opts: list[discord.SelectOption] = []

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Abra o seu próprio painel com `/menu`. 😉", ephemeral=True)
            return False
        return True

    def goto(self, screen: str) -> None:
        self.screen = screen
        self.page = 0

    # ---- ciclo de render ----
    async def render(self) -> tuple[discord.Embed, discord.File | None]:
        builder = getattr(self, f"_s_{self.screen}", self._s_home)
        emb, file = await builder()
        if self.flash:
            emb.add_field(name="​", value=self.flash, inline=False)
            self.flash = ""  # consumido: aparece uma vez
        return emb, file

    async def show(self, interaction: discord.Interaction) -> None:
        # defer primeiro (ack < 3s); depois geramos imagem com calma e editamos
        try:
            await interaction.response.defer()
        except discord.InteractionResponded:
            pass
        emb, file = await self.render()
        self._build()
        await interaction.edit_original_response(
            embed=emb, view=self, attachments=([file] if file else []))

    async def send_first(self, ctx: commands.Context, ephemeral: bool) -> None:
        emb, file = await self.render()
        self._build()
        self.message = await ctx.send(
            embed=emb, view=self, ephemeral=ephemeral, **({"file": file} if file else {}))

    async def on_timeout(self) -> None:
        for c in self.children:
            c.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    # ---- construção dos componentes por tela ----
    def _build(self) -> None:
        self.clear_items()
        s = self.screen
        if s == "home":
            self.add_item(NavBtn(self, "explorar", "Explorar", "🌿", discord.ButtonStyle.success, 0, action="explore"))
            self.add_item(NavBtn(self, "time", "Time", "🎒", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "colecao", "Coleção", "📦", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "loja", "Loja", "🛒", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "market", "Market", "🏪", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "liga", "Liga", "🏆", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "missoes", "Missões", "📋", discord.ButtonStyle.primary, 2))
            self.add_item(NavBtn(self, "perfil", "Perfil", "👤", discord.ButtonStyle.primary, 2))
            self.add_item(CloseBtn(self, row=2))
        elif s == "time":
            self.add_item(NavBtn(self, "time_select", "Adicionar", "➕", discord.ButtonStyle.success, 0, mode="add"))
            self.add_item(NavBtn(self, "time_select", "Remover", "➖", discord.ButtonStyle.danger, 0, mode="remove"))
            self.add_item(NavBtn(self, "time_select", "Líder", "⭐", discord.ButtonStyle.primary, 0, mode="lead"))
            self.add_item(HomeBtn(self, 1))
        elif s == "time_select":
            if self._opts:
                self.add_item(ChoiceSelect(self, "party", "Escolha um pokémon...", self._opts))
            self.add_item(NavBtn(self, "time", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "colecao":
            if self._opts:
                self.add_item(ChoiceSelect(self, "detail", "Ver detalhes de...", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(HomeBtn(self, 1))
        elif s == "detalhe":
            self.add_item(ActionBtn(self, "fav", "Favoritar", "❤️", discord.ButtonStyle.secondary, 0))
            self.add_item(ActionBtn(self, "lead", "Tornar líder", "⭐", discord.ButtonStyle.primary, 0))
            self.add_item(ActionBtn(self, "evolve", "Evoluir", "🧬", discord.ButtonStyle.success, 0))
            self.add_item(ActionBtn(self, "release", "Soltar", "🔁", discord.ButtonStyle.danger, 0))
            self.add_item(NavBtn(self, "colecao", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "evolve_choice":
            for opt in self._opts:
                self.add_item(EvoBtn(self, int(opt.value), opt.label))
            self.add_item(NavBtn(self, "detalhe", "Cancelar", "🛑", discord.ButtonStyle.secondary, 1))
        elif s == "release_confirm":
            self.add_item(ActionBtn(self, "release_yes", "Confirmar", "✅", discord.ButtonStyle.danger, 0))
            self.add_item(NavBtn(self, "detalhe", "Cancelar", "🛑", discord.ButtonStyle.secondary, 0))
        elif s == "loja":
            if self._opts:
                self.add_item(ChoiceSelect(self, "shop", "Comprar item...", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(HomeBtn(self, 1))
        elif s == "loja_buy":
            for q in (1, 5, 10, 25):
                self.add_item(BuyBtn(self, q))
            self.add_item(NavBtn(self, "loja", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "market":
            if self._opts:
                self.add_item(ChoiceSelect(self, "market", "Comprar do mercado...", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(HomeBtn(self, 1))
        elif s == "market_buy":
            self.add_item(ActionBtn(self, "market_yes", "Comprar", "💰", discord.ButtonStyle.success, 0))
            self.add_item(NavBtn(self, "market", "Voltar", "◀️", discord.ButtonStyle.secondary, 0))
        elif s == "missoes":
            self.add_item(ActionBtn(self, "daily", "Resgatar diário", "🎁", discord.ButtonStyle.success, 0))
            self.add_item(ActionBtn(self, "quests", "Resgatar missões", "📋", discord.ButtonStyle.success, 0))
            self.add_item(HomeBtn(self, 1))
        elif s == "liga":
            self.add_item(NavBtn(self, "liga_badges", "Insígnias", "🎖️", discord.ButtonStyle.primary, 0))
            self.add_item(HomeBtn(self, 0))
        elif s == "explorar":
            phase = (self.encounter or {}).get("phase") if self.encounter else None
            if self.encounter and phase == "main":
                self.add_item(ActionBtn(self, "capturar", "Capturar", "🎯", discord.ButtonStyle.success, 0))
                self.add_item(ActionBtn(self, "batalhar", "Batalhar", "⚔️", discord.ButtonStyle.primary, 0))
                self.add_item(ActionBtn(self, "ignorar", "Ignorar", "🏃", discord.ButtonStyle.secondary, 0))
            elif self.encounter and phase == "ball":
                for opt in self._opts:
                    self.add_item(BallBtn(self, opt.value, opt.label))
                self.add_item(ActionBtn(self, "ball_back", "Voltar", "↩️", discord.ButtonStyle.secondary, 1))
            else:
                self.add_item(NavBtn(self, "explorar", "Explorar de novo", "🌿", discord.ButtonStyle.success, 0, action="explore"))
                self.add_item(HomeBtn(self, 0))
        else:  # liga_badges e afins
            self.add_item(NavBtn(self, "liga" if s == "liga_badges" else "home",
                                 "Voltar" if s == "liga_badges" else "Início",
                                 "◀️" if s == "liga_badges" else "🏠",
                                 discord.ButtonStyle.secondary, 0))

    # ==================================================================
    #  TELAS (builders _s_<screen>)
    # ==================================================================
    async def _s_home(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            total = await helpers.pokemon_count(session, user.id)
            dex = await session.scalar(select(func.count(PokedexEntry.id)).where(
                PokedexEntry.user_id == user.id, PokedexEntry.caught > 0)) or 0
            sel = await helpers.get_selected(session, user)
            lider = POKEDEX.get(sel.species_id).name if sel else "—"
            coins, badges, slots = user.coins, user.badge_count, party_slots(user.badges)
            sel_id = sel.species_id if sel else 25
        emb = discord.Embed(
            title="🎮 Central PokeM1D",
            description=(f"💰 **{coins:,}** PokéCoins\n"
                        f"🎒 Time **{slots} slots**  ·  ⭐ Líder: **{lider}**\n"
                        f"📦 Coleção: **{total}**  ·  📕 Pokédex: **{dex}/{POKEDEX.count()}**\n"
                        f"🏅 Insígnias: **{badges}**\n\nEscolha uma opção. 👇"),
            color=settings.color_default)
        emb.set_thumbnail(url=settings.sprite_animated(sel_id))
        return emb, None

    async def _s_perfil(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            total = await helpers.pokemon_count(session, user.id)
            dex = await session.scalar(select(func.count(PokedexEntry.id)).where(
                PokedexEntry.user_id == user.id, PokedexEntry.caught > 0)) or 0
            d = dict(level=user.trainer_level, xp=user.trainer_xp, nxt=user.xp_to_next,
                     coins=user.coins, caught=user.total_caught, shiny=user.total_shiny,
                     bw=user.battles_won, bt=user.battles_total, ach=len(user.achievements or []),
                     streak=user.daily_streak, badges=user.badge_count)
        wr = (d["bw"] / d["bt"] * 100) if d["bt"] else 0
        emb = discord.Embed(title="👤 Perfil de treinador", color=settings.color_default)
        for nome, val in [("Nível", f"{d['level']} ({d['xp']}/{d['nxt']})"), ("PokéCoins", f"{d['coins']:,}"),
                          ("Streak", f"🔥 {d['streak']}"), ("Capturas", f"{d['caught']:,}"),
                          ("Shinies", f"✨ {d['shiny']}"), ("Coleção", str(total)),
                          ("Pokédex", f"{dex}/{POKEDEX.count()}"), ("Batalhas", f"{d['bw']}V ({wr:.0f}%)"),
                          ("Conquistas", f"🏆 {d['ach']}/{len(ACHIEVEMENTS)}")]:
            emb.add_field(name=nome, value=val, inline=True)
        return emb, None

    async def _s_time(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            party, pmax = list(user.party or []), party_slots(user.badges)
            members = []
            for pos, idx in enumerate(party, 1):
                poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                if poke:
                    sp = POKEDEX.get(poke.species_id)
                    members.append(dict(species_id=sp.id, shiny=poke.shiny, name=sp.name,
                                        level=poke.level, iv=poke.iv_percent, idx=idx, lead=pos == 1))
        emb = discord.Embed(title=f"🎒 Seu time ({len(members)}/{pmax})", color=settings.color_default)
        if not members:
            emb.description = "Time vazio. Use ➕ Adicionar para montar (até " + str(pmax) + ")."
            return emb, None
        buf = await render_team(members)
        file = discord.File(buf, filename="team.png") if buf else None
        if file:
            emb.set_image(url="attachment://team.png")
        emb.description = "👑 O líder bate primeiro e define o nível dos encontros."
        return emb, file

    async def _s_time_select(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            party, pmax = list(user.party or []), party_slots(user.badges)
            self._opts = []
            if self.select_mode == "add":
                mons = await helpers.list_pokemon(session, user.id)
                for m in mons:
                    if m.idx in party:
                        continue
                    sp = POKEDEX.get(m.species_id)
                    if sp:
                        self._opts.append(discord.SelectOption(
                            label=f"#{m.idx} {sp.name}"[:100], description=f"Nv {m.level} · IV {m.iv_percent:.0f}%",
                            value=str(m.idx)))
                    if len(self._opts) >= 25:
                        break
                titulo, desc = "➕ Adicionar ao time", f"Escolha quem entra (time {len(party)}/{pmax})."
            else:
                for idx in party:
                    poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                    if poke:
                        sp = POKEDEX.get(poke.species_id)
                        self._opts.append(discord.SelectOption(
                            label=f"#{idx} {sp.name}"[:100], description=f"Nv {poke.level}", value=str(idx)))
                titulo = "➖ Remover do time" if self.select_mode == "remove" else "⭐ Definir líder"
                desc = "Escolha um pokémon do seu time."
        emb = discord.Embed(title=titulo, description=desc, color=settings.color_info)
        if not self._opts:
            emb.description = "Nenhum pokémon disponível para essa ação."
        return emb, None

    async def _s_colecao(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            mons = await helpers.list_pokemon(session, user.id)
        rows = [(m, POKEDEX.get(m.species_id)) for m in mons]
        rows = [(m, sp) for m, sp in rows if sp]
        self._opts = []
        if not rows:
            return discord.Embed(title="📦 Coleção", color=settings.color_info,
                                 description=f"Vazia! Use 🌿 Explorar para achar pokémon."), None
        pages = max(1, (len(rows) + PER_PAGE_DEX - 1) // PER_PAGE_DEX)
        self.page %= pages
        sl = rows[self.page * PER_PAGE_DEX:(self.page + 1) * PER_PAGE_DEX]
        entries = [(sp.id, m.shiny, sp.name, f"#{m.idx} Nv{m.level}") for m, sp in sl]
        self._opts = [discord.SelectOption(label=f"#{m.idx} {sp.name}"[:100],
                                           description=f"Nv {m.level} · IV {m.iv_percent:.0f}%", value=str(m.idx))
                      for m, sp in sl]
        emb = discord.Embed(title=f"📦 Coleção ({len(rows)}) — pág {self.page + 1}/{pages}", color=settings.color_info)
        buf = await render_grid(entries, cols=3)
        file = discord.File(buf, filename="dex.png") if buf else None
        if file:
            emb.set_image(url="attachment://dex.png")
        emb.set_footer(text="Escolha no menu para ver detalhes • ✨ dourado = shiny")
        return emb, file

    async def _s_detalhe(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            if poke is None:
                self.goto("colecao")
                return await self._s_colecao()
            sp = POKEDEX.get(poke.species_id)
            data = dict(name=sp.name, idx=poke.idx, lv=poke.level, iv=poke.iv_percent,
                        shiny=poke.shiny, fav=poke.favorite, types=sp.types, sid=sp.id, rarity=sp.rarity,
                        evos=sp.eligible_level_evos(poke.level), all_level=[e for e in sp.evolutions if e.method == "level"])
        types = " ".join(f"{t.title()}" for t in data["types"])
        emb = discord.Embed(
            title=f"{'✨ ' if data['shiny'] else ''}{data['name']}  #{data['idx']}",
            color=settings.color_shiny if data["shiny"] else settings.color_default,
            description=(f"{RARITY_EMOJI.get(data['rarity'],'')} {rarity_label(data['rarity'])} · {types}\n"
                        f"**Nível {data['lv']}** · IV **{data['iv']:.1f}%**\n"
                        f"{'❤️ Favorito' if data['fav'] else '🤍 Não favorito'}"))
        emb.set_image(url=settings.sprite_animated(data["sid"], shiny=data["shiny"]))
        if data["evos"]:
            alvos = ", ".join(POKEDEX.get(e.to).name for e in data["evos"])
            emb.add_field(name="🧬 Pode evoluir para", value=alvos, inline=False)
        elif data["all_level"]:
            need = min(e.level for e in data["all_level"])
            emb.add_field(name="🧬 Evolução", value=f"No nível {need}.", inline=False)
        return emb, None

    async def _s_evolve_choice(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            sp = POKEDEX.get(poke.species_id) if poke else None
            steps = sp.eligible_level_evos(poke.level) if sp else []
            self._opts = [discord.SelectOption(label=POKEDEX.get(s.to).name, value=str(s.to)) for s in steps]
            nome = sp.name if sp else "?"
        emb = discord.Embed(title="🔀 Evolução paralela",
                            description=f"Para qual forma **{nome}** deve evoluir?", color=settings.color_info)
        return emb, None

    async def _s_release_confirm(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            if poke is None:
                self.goto("colecao")
                return await self._s_colecao()
            sp = POKEDEX.get(poke.species_id)
            fav, reward, nome, lv = poke.favorite, 50 + poke.level * 3, sp.name, poke.level
        if fav:
            emb = discord.Embed(title="🔒 Favorito protegido",
                                description=f"**{nome}** é favorito. Desfavorite antes de soltar.",
                                color=settings.color_error)
        else:
            emb = discord.Embed(title="🔁 Soltar pokémon?",
                                description=f"Soltar **{nome}** (Nv {lv}) por **+{reward}** 🪙?\n"
                                            f"⚠️ Permanente! (a Pokédex não é afetada)", color=settings.color_error)
        return emb, None

    async def _s_loja(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            coins = user.coins
        itens = [ITEMS[k] for k in SHOP_ORDER if ITEMS[k].price > 0]
        pages = max(1, (len(itens) + PER_PAGE_SHOP - 1) // PER_PAGE_SHOP)
        self.page %= pages
        sl = itens[self.page * PER_PAGE_SHOP:(self.page + 1) * PER_PAGE_SHOP]
        self._opts = [discord.SelectOption(label=f"{it.name} — {it.price:,}🪙"[:100],
                                           description=it.description[:100], value=it.key, emoji=it.emoji)
                      for it in sl]
        linhas = [f"{it.emoji} **{it.name}** — `{it.price:,}` 🪙\n   ↳ {it.description}" for it in sl]
        emb = discord.Embed(title=f"🛒 PokéMart — pág {self.page + 1}/{pages}",
                            description="\n".join(linhas), color=settings.color_info)
        emb.set_footer(text=f"Saldo: {coins:,} 🪙 • escolha no menu para comprar")
        return emb, None

    async def _s_loja_buy(self):
        it = get_item(self.shop_key)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            coins = user.coins
        emb = discord.Embed(title=f"{it.emoji} {it.name}",
                            description=(f"{it.description}\n\nPreço: **{it.price:,}** 🪙 cada\n"
                                        f"Seu saldo: **{coins:,}** 🪙\n\nEscolha a quantidade:"),
                            color=settings.color_info)
        return emb, None

    async def _s_market(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            coins = user.coins
            res = await session.scalars(select(MarketListing).where(
                MarketListing.active == True).order_by(MarketListing.price))  # noqa: E712
            data = []
            for lst in res:
                poke = await session.get(Pokemon, lst.pokemon_id)
                if poke is None:
                    continue
                sp = POKEDEX.get(poke.species_id)
                data.append((lst.id, sp.name, poke.level, poke.iv_percent, poke.shiny, lst.price, lst.seller_id))
        self._opts = []
        if not data:
            return discord.Embed(title="🏪 Mercado", color=settings.color_info,
                                 description=f"Nenhum pokémon à venda.\nAnuncie com `{self.prefix}market add <#> <preço>`."), None
        pages = max(1, (len(data) + PER_PAGE_MARKET - 1) // PER_PAGE_MARKET)
        self.page %= pages
        sl = data[self.page * PER_PAGE_MARKET:(self.page + 1) * PER_PAGE_MARKET]
        linhas = []
        for lid, nome, lv, iv, shiny, preco, seller in sl:
            s = "✨" if shiny else ""
            linhas.append(f"`{lid}` {s}**{nome}** Nv{lv} IV{iv:.0f}% — **{preco:,}**🪙")
            if seller != self.author_id:
                self._opts.append(discord.SelectOption(label=f"{nome} Nv{lv} — {preco:,}🪙"[:100],
                                                       description=f"IV {iv:.0f}% · ID {lid}", value=str(lid)))
        emb = discord.Embed(title=f"🏪 Mercado — pág {self.page + 1}/{pages}",
                            description="\n".join(linhas), color=settings.color_info)
        emb.set_footer(text=f"Saldo: {coins:,} 🪙 • anunciar: {self.prefix}market add <#> <preço>")
        return emb, None

    async def _s_market_buy(self):
        async with session_scope() as session:
            lst = await session.get(MarketListing, self.market_id)
            user = await helpers.fetch_user(session, self.author_id)
            coins = user.coins
            if lst is None or not lst.active:
                self.goto("market")
                return await self._s_market()
            poke = await session.get(Pokemon, lst.pokemon_id)
            sp = POKEDEX.get(poke.species_id) if poke else None
            nome, lv, iv, shiny, preco, sid = (sp.name if sp else "?"), (poke.level if poke else 0), \
                (poke.iv_percent if poke else 0), (poke.shiny if poke else False), lst.price, (sp.id if sp else 25)
        emb = discord.Embed(title=f"🏪 Comprar {('✨' if shiny else '')}{nome}",
                            description=(f"Nível {lv} · IV {iv:.1f}%\nPreço: **{preco:,}** 🪙\n"
                                        f"Seu saldo: **{coins:,}** 🪙"),
                            color=settings.color_info)
        emb.set_thumbnail(url=settings.sprite_animated(sid, shiny=shiny))
        return emb, None

    async def _s_missoes(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            state = quest_state(user)
            last, streak = user.last_daily, user.daily_streak
        agora = datetime.now(timezone.utc)
        daily_ok = last is None or (last.replace(tzinfo=timezone.utc) if last.tzinfo is None else last).date() != agora.date()
        linhas = []
        for q, cur, done, claimed in state:
            bar = "✅" if (done and claimed) else ("🎁" if done else "⬜")
            linhas.append(f"{bar} **{q.description}** — {min(cur, q.goal)}/{q.goal} (+{q.reward_coins}🪙/+{q.reward_xp}XP)")
        emb = discord.Embed(title="📋 Missões & Diário",
                            description=(f"🎁 **Diário**: {'pronto!' if daily_ok else 'já resgatado hoje'} · 🔥 {streak}\n\n"
                                        + "\n".join(linhas)), color=settings.color_default)
        return emb, None

    async def _s_liga(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            badges, slots = set(user.badges or []), party_slots(user.badges)
        linhas = []
        for i, c in enumerate(CHALLENGES):
            st = "✅" if c.key in badges else ("▶️" if (i == 0 or CHALLENGES[i - 1].key in badges) else "🔒")
            tag = {"champion": "👑 ", "elite": "⭐ ", "legend": "🌟 ", "myth": "💠 "}.get(c.kind, "")
            linhas.append(f"{st} `{i + 1:>2}` {c.emoji} {tag}**{c.name}** — {c.leader}")
        emb = discord.Embed(title=f"🏆 Liga ({len(badges)}/{len(CHALLENGES)})",
                            description="\n".join(linhas), color=settings.color_default)
        emb.set_footer(text=f"Time: {slots} slots • desafie com {self.prefix}gym <nº/nome>")
        return emb, None

    async def _s_liga_badges(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            blist = list(user.badges or [])
        earned = [CHALLENGES_BY_KEY[k] for k in blist if k in CHALLENGES_BY_KEY]
        desc = (f"Nenhuma insígnia ainda. Comece em `{self.prefix}gym 1`!" if not earned
                else "  ".join(c.emoji for c in earned) + "\n\n"
                + "\n".join(f"{c.emoji} **{c.badge}** — {c.name}" for c in earned))
        return discord.Embed(title=f"🎖️ Insígnias ({len(earned)}/{len(CHALLENGES)})",
                             description=desc, color=settings.color_default), None

    async def _s_explorar(self):
        enc = self.encounter
        if enc and enc.get("phase") in ("main", "ball"):
            from bot.utils.explore_scene import render_explore_scene
            sp = enc["species"]
            name = ("✨ " if enc["shiny"] else "") + sp.name
            types = " ".join(f"{t.title()}" for t in sp.types)
            if enc["phase"] == "main":
                desc = (f"📍 *{enc['location']}*\n\n**{name}** • Nv {enc['level']}\n"
                        f"{RARITY_EMOJI.get(sp.rarity,'')} {rarity_label(sp.rarity)} · {types}\n\nO que deseja fazer?")
            else:
                from bot.cogs.explore import CATCH_CHANCE, BALL_CATCH_BONUS, BALL_ORDER
                owned = getattr(self, "_ball_owned", {})
                self._opts = []
                for key in BALL_ORDER:
                    if owned.get(key, 0) > 0:
                        it = get_item(key)
                        ch = int(min(CATCH_CHANCE.get(sp.rarity, 0.5) + BALL_CATCH_BONUS.get(key, 0.0), 1.0) * 100)
                        self._opts.append(discord.SelectOption(
                            label=f"{it.name} (×{owned[key]}) • {ch}%", value=key))
                desc = f"🎯 Escolha a **pokébola** para capturar **{name}**:"
            emb = discord.Embed(title=f"🌿 Um {sp.name} selvagem apareceu!",
                                description=desc, color=settings.color_default)
            buf = await render_explore_scene("pokemon", sp, enc["shiny"])
            file = discord.File(buf, filename="explore.png") if buf else None
            if file:
                emb.set_image(url="attachment://explore.png")
            return emb, file
        # tela de resultado (nada / moedas / capturado / fugiu / batalha)
        from bot.utils.explore_scene import render_explore_scene
        kind, info = (self.result or ("nothing", ""))
        scene = "coins" if kind == "coins" else "nothing"
        titulos = {"nothing": "🔍 Exploração", "coins": "💰 Tesouro!", "caught": "🎉 Captura!",
                   "fled": "💨 Escapou!", "battle": "⚔️ Batalha!", "cooldown": "⏳ Calma!"}
        emb = discord.Embed(title=titulos.get(kind, "🔍 Exploração"), description=info, color=settings.color_info)
        if kind in ("nothing", "coins"):
            buf = await render_explore_scene(scene)
            file = discord.File(buf, filename="explore.png") if buf else None
            if file:
                emb.set_image(url="attachment://explore.png")
            return emb, file
        return emb, None

    # ==================================================================
    #  AÇÕES
    # ==================================================================
    async def do_explore(self, interaction: discord.Interaction) -> None:
        now = time.time()
        cd = getattr(settings, "explore_cooldown_seconds", 5)
        if now - self.last_explore < cd:
            self.encounter = None
            self.result = ("cooldown", f"Espere mais **{cd - (now - self.last_explore):.0f}s** para explorar de novo.")
            self.goto("explorar")
            return await self.show(interaction)
        self.last_explore = now
        self.goto("explorar")
        from bot.cogs.explore import LOCATIONS
        location = random.choice(LOCATIONS)
        roll = random.random()
        if roll < settings.explore_nothing_chance:
            self.encounter = None
            self.result = ("nothing", f"📍 *{location}*\nNada por aqui... tente de novo.")
            return await self.show(interaction)
        if roll < settings.explore_nothing_chance + settings.explore_coins_chance:
            coins = random.randint(settings.explore_coins_min, settings.explore_coins_max)
            async with session_scope() as session:
                user = await helpers.fetch_user(session, self.author_id)
                user.coins += coins
            self.encounter = None
            self.result = ("coins", f"📍 *{location}*\nVocê achou **{coins} PokéCoins**! 💰")
            return await self.show(interaction)
        # encontro
        species = pick_spawn_species()
        shiny = roll_shiny(settings.shiny_chance)
        from bot.cogs.explore import roll_encounter_level
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            party = list(user.party or [])
            lead_level = None
            if party:
                lead = await helpers.get_pokemon_by_idx(session, user.id, party[0])
                lead_level = lead.level if lead else None
            if lead_level is None:
                sel = await helpers.get_selected(session, user)
                lead_level = sel.level if sel else 5
            await helpers.update_pokedex(session, user.id, species.id, seen=1, caught=0)
        level = roll_encounter_level(species, lead_level)
        self.encounter = {"species": species, "shiny": shiny, "level": level,
                          "location": location, "phase": "main"}
        self.result = None
        await self.show(interaction)

    async def do_action(self, interaction: discord.Interaction, action: str) -> None:
        # --- resgates ---
        if action in ("daily", "quests"):
            async with session_scope() as session:
                user = await helpers.fetch_user(session, self.author_id)
                if action == "daily":
                    _, self.flash = _claim_daily(user)
                else:
                    ganhos = []
                    for q, cur, done, claimed in quest_state(user):
                        if done and not claimed and (c := claim_quest(user, q.key)):
                            user.coins += c.reward_coins
                            helpers.grant_trainer_xp(user, c.reward_xp)
                            ganhos.append(c)
                    self.flash = (f"🎉 +{sum(q.reward_coins for q in ganhos):,}🪙 e "
                                  f"+{sum(q.reward_xp for q in ganhos)} XP!" if ganhos
                                  else "Nenhuma missão concluída para resgatar.")
            return await self.show(interaction)

        # --- detalhe: favoritar / líder / evoluir / soltar ---
        if action in ("fav", "lead", "evolve", "release", "release_yes"):
            return await self._detail_action(interaction, action)

        # --- explorar ---
        if action in ("capturar", "batalhar", "ignorar", "ball_back"):
            return await self._explore_action(interaction, action)

        # --- loja / market confirm ---
        if action == "market_yes":
            return await self._market_buy(interaction)

    async def _detail_action(self, interaction, action):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            if poke is None:
                self.flash = "Pokémon não encontrado."
                self.goto("colecao")
                return await self.show(interaction)
            sp = POKEDEX.get(poke.species_id)
            if action == "fav":
                poke.favorite = not poke.favorite
                self.flash = f"{sp.name} {'favoritado ❤️' if poke.favorite else 'desfavoritado 🤍'}."
            elif action == "lead":
                user.selected_id = poke.id
                party = [poke.idx] + [x for x in (user.party or []) if x != poke.idx]
                user.party = party[:party_slots(user.badges)]
                self.flash = f"⭐ {sp.name} agora é o líder do time."
            elif action == "evolve":
                steps = sp.eligible_level_evos(poke.level)
                if not steps:
                    lv = [e for e in sp.evolutions if e.method == "level"]
                    self.flash = (f"{sp.name} evolui no nível {min(e.level for e in lv)}." if lv
                                  else f"{sp.name} não evolui por nível.")
                elif len(steps) == 1:
                    await self._do_evolve(session, user, poke, steps[0].to)
                else:
                    self.goto("evolve_choice")
                    return await self.show(interaction)
            elif action == "release":
                self.goto("release_confirm")
                return await self.show(interaction)
            elif action == "release_yes":
                if poke.favorite:
                    self.flash = "Favorito protegido. Desfavorite antes."
                else:
                    reward = 50 + poke.level * 3
                    if user.selected_id == poke.id:
                        user.selected_id = None
                    user.party = [p for p in (user.party or []) if p != poke.idx]
                    await session.delete(poke)
                    user.coins += reward
                    self.flash = f"👋 Soltou {sp.name} por +{reward} 🪙."
                    self.goto("colecao")
                    return await self.show(interaction)
        await self.show(interaction)

    async def _do_evolve(self, session, user, poke, target_to):
        from bot.cogs.evolution import perform_evolution
        from bot.utils.progression import bump_quest
        before = POKEDEX.get(poke.species_id).name
        step = next((s for s in POKEDEX.get(poke.species_id).eligible_level_evos(poke.level)
                     if s.to == target_to), None)
        if step is None:
            self.flash = "Evolução não disponível."
            return
        new = await perform_evolution(session, poke, step)
        await helpers.update_pokedex(session, user.id, new.id, seen=1, caught=1)
        bump_quest(user, "evolve", 1)
        self.flash = f"✨ {before} evoluiu para **{new.name}**!"

    async def evolve_to(self, interaction, target_to):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            if poke:
                await self._do_evolve(session, user, poke, target_to)
        self.goto("detalhe")
        await self.show(interaction)

    async def party_action(self, interaction, idx: int):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            party, pmax = list(user.party or []), party_slots(user.badges)
            poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
            if poke is None:
                self.flash = "Pokémon não é seu."
            elif self.select_mode == "add":
                if idx in party:
                    self.flash = "Já está no time."
                elif len(party) >= pmax:
                    self.flash = f"Time cheio ({pmax})."
                else:
                    party.append(idx)
                    user.party = party
                    self.flash = f"➕ #{idx} entrou no time."
            elif self.select_mode == "remove":
                user.party = [p for p in party if p != idx]
                self.flash = f"➖ #{idx} saiu do time."
            elif self.select_mode == "lead":
                user.selected_id = poke.id
                user.party = ([idx] + [p for p in party if p != idx])[:pmax]
                self.flash = f"⭐ #{idx} agora é o líder."
        self.goto("time")
        await self.show(interaction)

    async def open_detail(self, interaction, idx: int):
        self.detail_idx = idx
        self.goto("detalhe")
        await self.show(interaction)

    async def open_shop_item(self, interaction, key: str):
        self.shop_key = key
        self.goto("loja_buy")
        await self.show(interaction)

    async def buy_item(self, interaction, qty: int):
        it = get_item(self.shop_key)
        custo = it.price * qty
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            if user.coins < custo:
                self.flash = f"Saldo insuficiente ({custo:,} 🪙)."
            else:
                user.coins -= custo
                nova = await helpers.add_item(session, user.id, it.key, qty)
                self.flash = f"🛒 Comprou {qty}× {it.name} por {custo:,} 🪙. (tem {nova})"
        await self.show(interaction)

    async def open_market_listing(self, interaction, lid: int):
        self.market_id = lid
        self.goto("market_buy")
        await self.show(interaction)

    async def _market_buy(self, interaction):
        async with session_scope() as session:
            lst = await session.get(MarketListing, self.market_id)
            buyer = await helpers.fetch_user(session, self.author_id)
            if lst is None or not lst.active:
                self.flash = "Anúncio não existe mais."
            elif lst.seller_id == buyer.id:
                self.flash = "É o seu próprio anúncio."
            elif buyer.coins < lst.price:
                self.flash = f"Saldo insuficiente ({lst.price:,} 🪙)."
            else:
                poke = await session.get(Pokemon, lst.pokemon_id)
                if poke is None:
                    lst.active = False
                    self.flash = "O pokémon não existe mais."
                else:
                    seller = await session.get(User, lst.seller_id)
                    buyer.coins -= lst.price
                    if seller:
                        seller.coins += lst.price
                    poke.owner_id = buyer.id
                    poke.idx = buyer.next_idx
                    buyer.next_idx += 1
                    poke.favorite = False
                    lst.active = False
                    self.flash = f"💰 Comprou {POKEDEX.get(poke.species_id).name} por {lst.price:,} 🪙!"
        self.goto("market")
        await self.show(interaction)

    async def _explore_action(self, interaction, action):
        enc = self.encounter
        if not enc:
            return await self.show(interaction)
        if action == "ignorar":
            self.encounter = None
            self.result = ("nothing", "Você seguiu em frente. 🏃")
            return await self.show(interaction)
        if action == "ball_back":
            enc["phase"] = "main"
            return await self.show(interaction)
        if action == "capturar":
            from bot.cogs.explore import BALL_ORDER
            async with session_scope() as session:
                user = await helpers.fetch_user(session, self.author_id)
                inv = await helpers.get_inventory(session, user.id)
            owned = {k: inv.get(k, 0) for k in BALL_ORDER if inv.get(k, 0) > 0}
            if not owned:
                self.flash = "🎒 Sem pokébolas! Compre na Loja ou escolha Batalhar."
                return await self.show(interaction)
            self._ball_owned = owned
            enc["phase"] = "ball"
            return await self.show(interaction)
        if action == "batalhar":
            return await self._explore_battle(interaction)

    async def _explore_capture(self, interaction, ball_key):
        from bot.cogs.explore import do_capture, CATCH_CHANCE, BALL_CATCH_BONUS
        enc = self.encounter
        sp, level, shiny = enc["species"], enc["level"], enc["shiny"]
        item = get_item(ball_key)
        chance = min(CATCH_CHANCE.get(sp.rarity, 0.5) + BALL_CATCH_BONUS.get(ball_key, 0.0), 1.0)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            ok = await helpers.take_item(session, user.id, ball_key, 1)
        if not ok:
            self.flash = "Você não tinha essa bola."
            self.encounter = None
            self.result = ("fled", "Algo deu errado.")
            return await self.show(interaction)
        if not shiny:
            shiny = roll_shiny(settings.shiny_chance, item.shiny_bonus)
        self.encounter = None
        if random.random() >= chance:
            self.result = ("fled", f"💨 O **{sp.name}** se soltou e fugiu! (chance era {int(chance*100)}%)")
            return await self.show(interaction)
        idx, coins, new_dex, newly, iv_pct = await do_capture(
            self.ctx.bot, self.author_id, sp, level, shiny, item.catch_iv_rolls, item.min_iv_floor)
        extra = f"📊 IV {iv_pct:.1f}% · 💰 +{coins} 🪙 · #{idx}"
        if new_dex:
            extra += "\n📕 Novo registro na Pokédex!"
        if shiny:
            extra += "\n✨ **SHINY!**"
        self.result = ("caught", f"🎉 Você capturou **{sp.name}**!\n{extra}")
        await self.show(interaction)

    async def _explore_battle(self, interaction):
        enc = self.encounter
        battle_cog = self.ctx.bot.get_cog("Batalha")
        if battle_cog is None:
            self.flash = "Batalha indisponível."
            return await self.show(interaction)
        p1_team, err = await battle_cog.load_team(self.ctx, self.ctx.author)
        if not p1_team:
            self.flash = f"⚠️ {err}"
            return await self.show(interaction)
        sp, level, shiny = enc["species"], enc["level"], enc["shiny"]
        self.encounter = None
        self.result = ("battle", f"⚔️ Batalha contra **{sp.name}** (Nv {level}) iniciada **no canal**! "
                                 f"Boa sorte, treinador.")
        await self.show(interaction)
        from bot.cogs.battle import build_wild_mon
        p2_team = [build_wild_mon(sp, level, shiny=shiny)]
        species, explorer_id, ctx = sp, self.author_id, self.ctx

        async def on_finish(winner, loser):
            if winner.owner_id == explorer_id:
                await ctx.channel.send(embed=embeds.ok_embed(
                    "Vitória! 🏆", f"Você derrotou o **{species.name}** selvagem!"))
            else:
                await ctx.channel.send(embed=embeds.info_text(f"O **{species.name}** selvagem te derrotou... 💨"))

        await battle_cog.launch_battle(ctx, p1_team, p2_team, explorer_id, None, on_finish=on_finish)


# --------------------------------------------------------------------------
#  Componentes
# --------------------------------------------------------------------------
class NavBtn(discord.ui.Button):
    def __init__(self, view, target, label, emoji, style, row, *, mode=None, action=None):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._hub, self._t, self._mode, self._action = view, target, mode, action

    async def callback(self, interaction):
        if self._action == "explore":
            return await self._hub.do_explore(interaction)
        if self._mode:
            self._hub.select_mode = self._mode
        self._hub.goto(self._t)
        await self._hub.show(interaction)


class HomeBtn(NavBtn):
    def __init__(self, view, row):
        super().__init__(view, "home", "Início", "🏠", discord.ButtonStyle.secondary, row)


class PageBtn(discord.ui.Button):
    def __init__(self, view, delta, emoji, row):
        super().__init__(emoji=emoji, style=discord.ButtonStyle.secondary, row=row)
        self._hub, self._d = view, delta

    async def callback(self, interaction):
        self._hub.page += self._d
        await self._hub.show(interaction)


class ActionBtn(discord.ui.Button):
    def __init__(self, view, action, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._hub, self._a = view, action

    async def callback(self, interaction):
        await self._hub.do_action(interaction, self._a)


class EvoBtn(discord.ui.Button):
    def __init__(self, view, to, label):
        super().__init__(label=label, emoji="✨", style=discord.ButtonStyle.success, row=0)
        self._hub, self._to = view, to

    async def callback(self, interaction):
        await self._hub.evolve_to(interaction, self._to)


class BuyBtn(discord.ui.Button):
    def __init__(self, view, qty):
        super().__init__(label=f"x{qty}", style=discord.ButtonStyle.success, row=0)
        self._hub, self._q = view, qty

    async def callback(self, interaction):
        await self._hub.buy_item(interaction, self._q)


class BallBtn(discord.ui.Button):
    def __init__(self, view, key, label):
        it = get_item(key)
        super().__init__(label=label, emoji=it.emoji, style=discord.ButtonStyle.success, row=0)
        self._hub, self._key = view, key

    async def callback(self, interaction):
        await self._hub._explore_capture(interaction, self._key)


class ChoiceSelect(discord.ui.Select):
    def __init__(self, view, kind, placeholder, options, row=0):
        super().__init__(placeholder=placeholder, options=options[:25], row=row)
        self._hub, self._kind = view, kind

    async def callback(self, interaction):
        v = self.values[0]
        if self._kind == "detail":
            await self._hub.open_detail(interaction, int(v))
        elif self._kind == "party":
            await self._hub.party_action(interaction, int(v))
        elif self._kind == "shop":
            await self._hub.open_shop_item(interaction, v)
        elif self._kind == "market":
            await self._hub.open_market_listing(interaction, int(v))


class CloseBtn(discord.ui.Button):
    def __init__(self, view, row=2):
        super().__init__(label="Fechar", emoji="❌", style=discord.ButtonStyle.danger, row=row)
        self._hub = view

    async def callback(self, interaction):
        for c in self._hub.children:
            c.disabled = True
        await interaction.response.edit_message(
            content="Painel fechado. Abra de novo com `/menu`. 👋", embed=None, view=self._hub, attachments=[])
        self._hub.stop()


# ==========================================================================
class Hub(commands.Cog, name="Painel"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="menu", aliases=["jogar", "hub", "painel"])
    @commands.guild_only()
    async def menu(self, ctx: commands.Context) -> None:
        """Abre o painel central do jogo (use /menu para o modo privado)."""
        ephemeral = ctx.interaction is not None
        view = HubView(ctx)
        await view.send_first(ctx, ephemeral=ephemeral)

    @commands.command(name="sync")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context) -> None:
        """(Dono) Sincroniza os comandos de barra (/) neste servidor."""
        self.bot.tree.copy_global_to(guild=ctx.guild)
        synced = await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ {len(synced)} comando(s) de barra sincronizados aqui.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Hub(bot))
