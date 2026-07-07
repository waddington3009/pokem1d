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
from bot.data.gyms import CHALLENGES, CHALLENGES_BY_KEY, challenge_index, party_slots
from bot.data.items import ITEMS, SHOP_ORDER, find_item, get_item
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import MarketListing, PokedexEntry, Pokemon, User
from bot.utils import embeds, helpers
from bot.utils.images import render_grid
from bot.utils.progression import ACHIEVEMENTS, bump_quest, claim_quest, quest_state
from bot.utils.rarity import RARITY_EMOJI, pick_spawn_species, rarity_label, roll_shiny
from bot.utils.stats import apply_xp
from bot.utils.team_scene import render_team


def _stone_item_for(step):
    """Acha o item de pedra que dispara uma evolução por pedra."""
    for it in ITEMS.values():
        if it.category == "stone" and it.stone == step.stone:
            return it
    return None


def available_evos(sp, level: int, inv: dict) -> list[dict]:
    """Todas as evoluções DISPONÍVEIS agora: por nível já liberado + por pedra
    cuja pedra o jogador possui no inventário. Cada item: {to, name, stone, item}."""
    out: list[dict] = []
    for ev in sp.evolutions:
        if ev.method == "level" and ev.level is not None and level >= ev.level:
            out.append({"to": ev.to, "name": POKEDEX.get(ev.to).name, "stone": None, "item": None})
        elif ev.method == "stone":
            sit = _stone_item_for(ev)
            if sit and inv.get(sit.key, 0) > 0:
                out.append({"to": ev.to, "name": POKEDEX.get(ev.to).name,
                            "stone": sit.key, "item": sit})
    return out


def _evo_blocked_msg(sp, level: int) -> str:
    """Motivo de não poder evoluir agora (usado quando não há caminho disponível)."""
    stone_evos = [e for e in sp.evolutions if e.method == "stone"]
    level_evos = [e for e in sp.evolutions if e.method == "level"]
    if stone_evos:
        faltam = ", ".join(_stone_item_for(e).name for e in stone_evos if _stone_item_for(e))
        return f"🪨 Precisa de uma pedra: **{faltam}**. Compre na 🛒 Loja e tente de novo."
    if level_evos:
        need = min(e.level for e in level_evos)
        return f"{sp.name} evolui no **nível {need}** (faltam {max(0, need - level)})."
    return f"{sp.name} **não evolui mais** (forma final). 🏆"


def _evo_info(sp, level: int, inv: dict) -> tuple[str, str]:
    """Texto claro sobre a evolução: pronto (nível/pedra que tem), requisito ou nenhuma."""
    ready = available_evos(sp, level, inv)
    level_evos = [e for e in sp.evolutions if e.method == "level"]
    stone_evos = [e for e in sp.evolutions if e.method == "stone"]
    other_evos = [e for e in sp.evolutions if e.method in ("trade", "friendship")]
    if ready:
        alvos = []
        for o in ready:
            alvos.append(f"{o['name']} ({o['item'].emoji} {o['item'].name})" if o["stone"] else o["name"])
        return "🧬 Pronto para evoluir!", "→ **" + "**, **".join(alvos) + "**\nClique em **🧬 Evoluir** abaixo."
    # ainda não disponível — mostra requisitos
    parts = []
    if level_evos:
        need = min(e.level for e in level_evos)
        parts.append(f"⬆️ Evolui no **nível {need}** (faltam **{max(0, need - level)}** níveis).")
    for e in stone_evos:
        sit = _stone_item_for(e)
        if sit:
            parts.append(f"{sit.emoji} **{sit.name}** → {POKEDEX.get(e.to).name} ❌ compre na 🛒 Loja")
    if other_evos:
        parts.append("✨ Evolui por troca/amizade (em breve).")
    if parts:
        return "🧬 Evolução", "\n".join(parts)
    return "🔒 Evolução", "**Não evolui mais** — é a forma final! 🏆"

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
    # painel atualmente aberto por usuário (author_id -> HubView). Impede abrir
    # vários /menu ao mesmo tempo (cada um teria seu próprio cooldown de explorar,
    # o que permitiria burlar a espera entre explorações).
    _active_sessions: dict[int, "HubView"] = {}

    @classmethod
    def active_session(cls, author_id: int) -> "HubView | None":
        v = cls._active_sessions.get(author_id)
        return v if (v is not None and not v.is_finished()) else None

    def _register_active(self) -> None:
        HubView._active_sessions[self.author_id] = self

    def _deregister_active(self) -> None:
        if HubView._active_sessions.get(self.author_id) is self:
            HubView._active_sessions.pop(self.author_id, None)

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
        self.use_item_key: str | None = None       # item escolhido na mochila
        self.rank_type: str = "caught"             # categoria do ranking
        self.select_mode: str | None = None       # add | remove | lead
        self.dex_species_id: int | None = None     # espécie aberta na Pokédex
        self.col_filter: str = "all"               # filtro da coleção: all|shiny|fav|iv|type
        self.col_type: str | None = None           # tipo escolhido p/ filtro "type"
        self.encounter: dict | None = None         # {species, shiny, level, location, phase}
        self.result: tuple | None = None           # ('nothing'|'coins'|'caught'|'fled'|'battle', dados)
        self.last_explore = 0.0
        # True quando a mensagem foi "entregue" a uma batalha (evita o timeout do
        # hub sobrescrever a batalha em andamento na mesma mensagem ephemeral)
        self.handed_off = False
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
        self._deregister_active()   # libera o usuário para abrir um novo /menu
        if self.handed_off:   # a mensagem agora é de uma batalha — não mexer
            return
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
            self.add_item(NavBtn(self, "pesquisa", "Pesquisa", "🔬", discord.ButtonStyle.success, 0))
            self.add_item(NavBtn(self, "home", "Duelar", "⚔️", discord.ButtonStyle.success, 0, action="duel"))
            self.add_item(NavBtn(self, "colecao", "Coleção", "📦", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "time", "Time", "👥", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "loja", "Loja", "🛒", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "mochila", "Mochila", "🎒", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "market", "Market", "🏪", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "liga", "Liga", "🏆", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "missoes", "Missões", "📋", discord.ButtonStyle.primary, 2))
            self.add_item(NavBtn(self, "pokedex", "Pokédex", "📕", discord.ButtonStyle.primary, 2))
            self.add_item(NavBtn(self, "ranking", "Ranking", "📊", discord.ButtonStyle.primary, 2))
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
            if self.select_mode == "add":   # 'add' lista toda a coleção -> pagina
                self.add_item(PageBtn(self, -1, "◀️", 1))
                self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(NavBtn(self, "time", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "mochila":
            if self._opts:
                self.add_item(ChoiceSelect(self, "useitem", "Usar um item...", self._opts, row=0))
            self.add_item(HomeBtn(self, 1))
        elif s == "use_target":
            if self._opts:
                self.add_item(ChoiceSelect(self, "usetarget", "Usar em qual pokémon?", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(NavBtn(self, "mochila", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "ranking":
            cats = [("caught", "🎯"), ("shiny", "✨"), ("coins", "💰"),
                    ("battles", "⚔️"), ("level", "🎖️"), ("badges", "🏅")]
            for i, (t, e) in enumerate(cats):
                self.add_item(RankBtn(self, t, e, row=0 if i < 3 else 1))
            self.add_item(HomeBtn(self, 2))
        elif s == "colecao":
            if self._opts:
                self.add_item(ChoiceSelect(self, "detail", "Ver detalhes de...", self._opts, row=0))
            self.add_item(FilterBtn(self, "📂 Filtro", 1))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(HomeBtn(self, 1))
        elif s == "colecao_filtro":
            self.add_item(FilterChoiceSelect(self))
            self.add_item(NavBtn(self, "colecao", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "pokedex":
            if self._opts:
                self.add_item(ChoiceSelect(self, "dexview", "Ver detalhes da espécie...", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(HomeBtn(self, 1))
        elif s == "pokedex_detail":
            self.add_item(NavBtn(self, "pokedex", "Voltar", "◀️", discord.ButtonStyle.secondary, 0))
        elif s == "pesquisa":
            if getattr(self, "_hunt_ready", False):
                self.add_item(HuntBtn(self, "legendary", "Iniciar Caçada", "⚔️"))
            if getattr(self, "_mythic_ready", False):
                self.add_item(HuntBtn(self, "mythical", "Caçada Mítica", "🌈"))
            self.add_item(HomeBtn(self, 1))
        elif s == "detalhe":
            self.add_item(ActionBtn(self, "fav", "Favoritar", "❤️", discord.ButtonStyle.secondary, 0))
            self.add_item(ActionBtn(self, "lead", "Tornar líder", "⭐", discord.ButtonStyle.primary, 0))
            self.add_item(ActionBtn(self, "evolve", "Evoluir", "🧬", discord.ButtonStyle.success, 0))
            self.add_item(ActionBtn(self, "release", "Soltar", "🔁", discord.ButtonStyle.danger, 0))
            self.add_item(NavBtn(self, "colecao", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "evolve_choice":
            for i, opt in enumerate(self._opts[:20]):
                self.add_item(EvoBtn(self, int(opt.value), opt.label, row=i // 5))
            cancel_row = min(4, ((len(self._opts[:20]) - 1) // 5 + 1) if self._opts else 0)
            self.add_item(NavBtn(self, "detalhe", "Cancelar", "🛑", discord.ButtonStyle.secondary, cancel_row))
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
            self.add_item(BuyQtyBtn(self))
            self.add_item(NavBtn(self, "loja", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "market":
            if self._opts:
                self.add_item(ChoiceSelect(self, "market", "Comprar do mercado...", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(NavBtn(self, "market_sell", "Anunciar", "📢", discord.ButtonStyle.success, 1))
            self.add_item(HomeBtn(self, 1))
        elif s == "market_sell":
            if self._opts:
                self.add_item(ChoiceSelect(self, "sell", "Anunciar qual pokémon?", self._opts, row=0))
            self.add_item(PageBtn(self, -1, "◀️", 1))
            self.add_item(PageBtn(self, +1, "▶️", 1))
            self.add_item(NavBtn(self, "market", "Voltar", "◀️", discord.ButtonStyle.secondary, 1))
        elif s == "market_buy":
            self.add_item(ActionBtn(self, "market_yes", "Comprar", "💰", discord.ButtonStyle.success, 0))
            self.add_item(NavBtn(self, "market", "Voltar", "◀️", discord.ButtonStyle.secondary, 0))
        elif s == "missoes":
            self.add_item(ActionBtn(self, "daily", "Resgatar diário", "🎁", discord.ButtonStyle.success, 0))
            self.add_item(ActionBtn(self, "quests", "Resgatar missões", "📋", discord.ButtonStyle.success, 0))
            self.add_item(HomeBtn(self, 1))
        elif s == "liga":
            if self._opts:
                self.add_item(ChoiceSelect(self, "gym", "Desafiar um líder...", self._opts, row=0))
            self.add_item(NavBtn(self, "liga_badges", "Insígnias", "🎖️", discord.ButtonStyle.primary, 1))
            self.add_item(HomeBtn(self, 1))
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
            coins, badges, slots = user.coins, user.badge_count or 0, party_slots(user.badges)
            sel_id = sel.species_id if sel else 25
            sel_shiny = sel.shiny if sel else False
            tlevel = user.trainer_level
            from bot.utils.research import progress as _research_progress
            r_pts, r_cost, r_frac = _research_progress(user)
        dex_total = POKEDEX.count()
        r_pct = int(r_frac * 100)
        # mantém o cargo de TÍTULO do jogador em dia com o nível (cria/atribui se preciso)
        member = self.ctx.guild.get_member(self.author_id) if self.ctx.guild else None
        if member is not None:
            from bot.utils.titles import sync_member_title
            granted = await sync_member_title(member, tlevel)
            if granted:
                self.flash = f"🎖️ Novo título desbloqueado: **{granted}**!"
        # cartão visual (arte de fundo + valores + líder no quadro). Se a arte não
        # existir ou falhar, cai no embed de texto abaixo.
        from bot.utils.home_scene import render_home_card
        buf = await render_home_card(
            coins=coins, slots=slots, leader=lider, leader_id=sel_id, leader_shiny=sel_shiny,
            collection=total, dex=dex, dex_total=dex_total, badges=badges)
        pesq = f"🔬 Pesquisa: **{r_pct}%** ({r_pts:,}/{r_cost:,})" + (" — ⚔️ **Caçada pronta!**" if r_pct >= 100 else "")
        if buf is not None:
            emb = discord.Embed(color=settings.color_default,
                                description=f"{pesq}\nEscolha uma opção. 👇")
            emb.set_image(url="attachment://home.png")
            return emb, discord.File(buf, filename="home.png")
        emb = discord.Embed(
            title="🎮 Central PokeM1D",
            description=(f"💰 **{coins:,}** PokéCoins\n"
                        f"🎒 Time **{slots} slots**  ·  ⭐ Líder: **{lider}**\n"
                        f"📦 Coleção: **{total}**  ·  📕 Pokédex: **{dex}/{dex_total}**\n"
                        f"🏅 Insígnias: **{badges}**  ·  {pesq}\n\nEscolha uma opção. 👇"),
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
                cand = [m for m in mons if m.idx not in party and POKEDEX.get(m.species_id)]
                pages = max(1, (len(cand) + 24) // 25)
                self.page %= pages
                for m in cand[self.page * 25:(self.page + 1) * 25]:
                    sp = POKEDEX.get(m.species_id)
                    fav = "❤️ " if m.favorite else ""
                    self._opts.append(discord.SelectOption(
                        label=f"{fav}#{m.idx} {sp.name}"[:100],
                        description=f"Nv {m.level} · IV {m.iv_percent:.0f}% · {getattr(m, 'nature', '')}"[:100],
                        value=str(m.idx)))
                titulo = "➕ Adicionar ao time"
                desc = f"Escolha quem entra (time {len(party)}/{pmax}) — **pág {self.page + 1}/{pages}**."
            else:
                for idx in party:
                    poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                    if poke:
                        sp = POKEDEX.get(poke.species_id)
                        fav = "❤️ " if poke.favorite else ""
                        self._opts.append(discord.SelectOption(
                            label=f"{fav}#{idx} {sp.name}"[:100],
                            description=f"Nv {poke.level} · IV {poke.iv_percent:.0f}%"[:100], value=str(idx)))
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
        # --- filtros ---
        flt, ftxt = self.col_filter, "Todos"
        if flt == "shiny":
            rows = [(m, sp) for m, sp in rows if m.shiny]; ftxt = "✨ Shiny"
        elif flt == "fav":
            rows = [(m, sp) for m, sp in rows if m.favorite]; ftxt = "❤️ Favoritos"
        elif flt == "type" and self.col_type:
            rows = [(m, sp) for m, sp in rows if self.col_type in sp.types]
            ftxt = f"🔖 {self.col_type.title()}"
        if flt == "iv":
            rows.sort(key=lambda r: r[0].iv_percent, reverse=True); ftxt = "💎 Maior IV"
        self._opts = []
        if not rows:
            vazio = "Vazia! Use 🌿 Explorar para achar pokémon." if self.col_filter == "all" \
                else f"Nenhum pokémon no filtro **{ftxt}**. Toque em 📂 Filtro para trocar."
            return discord.Embed(title="📦 Coleção", color=settings.color_info, description=vazio), None
        pages = max(1, (len(rows) + PER_PAGE_DEX - 1) // PER_PAGE_DEX)
        self.page %= pages
        sl = rows[self.page * PER_PAGE_DEX:(self.page + 1) * PER_PAGE_DEX]
        sub = (lambda m: f"#{m.idx} IV{m.iv_percent:.0f}%") if flt == "iv" else (lambda m: f"#{m.idx} Nv{m.level}")
        entries = [(sp.id, m.shiny, sp.name, sub(m)) for m, sp in sl]
        self._opts = [discord.SelectOption(
            label=f"{'❤️ ' if m.favorite else ''}#{m.idx} {sp.name}"[:100],
            description=f"Nv {m.level} · IV {m.iv_percent:.0f}% · {getattr(m, 'nature', '')}"[:100], value=str(m.idx))
            for m, sp in sl]
        emb = discord.Embed(title=f"📦 Coleção ({len(rows)}) · {ftxt} — pág {self.page + 1}/{pages}",
                            color=settings.color_info)
        buf = await render_grid(entries, cols=3)
        file = discord.File(buf, filename="dex.png") if buf else None
        if file:
            emb.set_image(url="attachment://dex.png")
        emb.set_footer(text="Escolha no menu p/ detalhes • 📂 Filtro p/ ver por tipo/IV • ✨ dourado = shiny")
        return emb, file

    async def _s_colecao_filtro(self):
        from bot.data.types import TYPE_EMOJI
        self._opts = [
            discord.SelectOption(label="Todos", value="all", emoji="📦", default=self.col_filter == "all"),
            discord.SelectOption(label="Maior IV", value="iv", emoji="💎", default=self.col_filter == "iv"),
            discord.SelectOption(label="Shiny", value="shiny", emoji="✨", default=self.col_filter == "shiny"),
            discord.SelectOption(label="Favoritos", value="fav", emoji="❤️", default=self.col_filter == "fav"),
        ]
        for t in sorted(TYPE_EMOJI):
            self._opts.append(discord.SelectOption(
                label=f"Tipo: {t.title()}", value=f"type:{t}", emoji=TYPE_EMOJI.get(t) or None,
                default=self.col_filter == "type" and self.col_type == t))
        emb = discord.Embed(title="📂 Filtrar coleção",
                            description="Escolha como quer ver sua coleção:\n"
                                        "• **Maior IV** ordena do melhor IV pro pior\n"
                                        "• **Tipo: X** mostra só pokémon daquele tipo",
                            color=settings.color_info)
        return emb, None

    async def _s_pokedex(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            res = await session.scalars(select(PokedexEntry).where(PokedexEntry.user_id == user.id))
            entries = {e.species_id: e for e in res}
        allsp = POKEDEX.all()
        total = len(allsp)
        caught = sum(1 for e in entries.values() if e.caught > 0)
        seen = sum(1 for e in entries.values() if e.seen > 0)
        percent = caught / total * 100 if total else 0
        pages = max(1, (total + PER_PAGE_DEX - 1) // PER_PAGE_DEX)
        self.page %= pages
        sl = allsp[self.page * PER_PAGE_DEX:(self.page + 1) * PER_PAGE_DEX]
        grid, self._opts = [], []
        for sp in sl:
            e = entries.get(sp.id)
            if e and e.caught > 0:
                grid.append((sp.id, False, sp.name, f"#{sp.id:03d}", False))
                self._opts.append(discord.SelectOption(label=f"#{sp.id:03d} {sp.name}"[:100], value=str(sp.id)))
            elif e and e.seen > 0:
                grid.append((sp.id, False, sp.name, f"#{sp.id:03d} • visto", True))
                self._opts.append(discord.SelectOption(label=f"#{sp.id:03d} {sp.name} (visto)"[:100], value=str(sp.id)))
            else:
                grid.append((sp.id, False, "???", f"#{sp.id:03d}", True))
        emb = discord.Embed(
            title=f"📕 Pokédex — {caught}/{total} ({percent:.0f}%) · pág {self.page + 1}/{pages}",
            description=f"👁️ Vistos: **{seen}** · ✅ Capturados: **{caught}**",
            color=settings.color_default)
        buf = await render_grid(grid, cols=3)
        file = discord.File(buf, filename="pokedex.png") if buf else None
        if file:
            emb.set_image(url="attachment://pokedex.png")
        emb.set_footer(text="colorido = capturado · cinza = falta · escolha no menu p/ ver a espécie")
        return emb, file

    async def _s_pokedex_detail(self):
        sp = POKEDEX.get(self.dex_species_id)
        if sp is None:
            self.goto("pokedex")
            return await self._s_pokedex()
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            e = await session.scalar(select(PokedexEntry).where(
                PokedexEntry.user_id == user.id, PokedexEntry.species_id == sp.id))
            owned = await session.scalar(select(func.count(Pokemon.id)).where(
                Pokemon.owner_id == user.id, Pokemon.species_id == sp.id)) or 0
            caught = bool(e and e.caught > 0)
            seen = bool(e and e.seen > 0)
        labels = {"hp": "HP", "atk": "Atk", "def": "Def", "spa": "SpA", "spd": "SpD", "spe": "Spe"}
        stat_txt = "\n".join(f"`{labels[k]:<3}` **{sp.base_stats[k]:>3}**" for k in
                             ["hp", "atk", "def", "spa", "spd", "spe"])
        if sp.evolutions:
            evs = []
            for ev in sp.evolutions:
                tgt = POKEDEX.get(ev.to).name
                if ev.method == "level":
                    evs.append(f"→ **{tgt}** (Nv {ev.level})")
                elif ev.method == "stone":
                    sit = _stone_item_for(ev)
                    evs.append(f"→ **{tgt}** ({sit.emoji} {sit.name})" if sit else f"→ **{tgt}**")
                else:
                    evs.append(f"→ **{tgt}** ({ev.method})")
            evo_text = "\n".join(evs)
        else:
            evo_text = "Forma final 🏆"
        status = "✅ Capturado" if caught else ("👁️ Visto" if seen else "❔ Não descoberto")
        emb = discord.Embed(
            title=f"#{sp.id:03d} — {sp.name}",
            description=f"{RARITY_EMOJI.get(sp.rarity, '')} {rarity_label(sp.rarity)} · {embeds.types_line(sp)}\n"
                        f"{status}" + (f" · 🎒 você tem **{owned}**" if owned else ""),
            color=settings.color_default)
        emb.set_thumbnail(url=settings.sprite_animated(sp.id))
        emb.add_field(name=f"📊 Base ({sp.base_total})", value=stat_txt, inline=True)
        emb.add_field(name="🧬 Evolução", value=evo_text, inline=True)
        emb.add_field(name="⚔️ Golpes",
                      value=", ".join(m.replace("-", " ").title() for m in sp.moves) or "—", inline=False)
        return emb, None

    async def _s_pesquisa(self):
        from bot.utils.research import (progress, mythic_cost, mythic_unlocked,
                                        rp_reduced_active, rp_until_reduced)
        from bot.utils.research_scene import render_research_card
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            pts, cost, frac = progress(user)
            reduced = rp_reduced_active(user)
            until_reduced = rp_until_reduced(user)
            myth_ok = mythic_unlocked(user)
            myth_pts, myth_cost, hunts = (user.research_points or 0), mythic_cost(), (user.hunts_won or 0)
        self._hunt_ready = pts >= cost
        self._mythic_ready = myth_ok and myth_pts >= myth_cost
        emb = discord.Embed(title="🔬 Pesquisa de Campo", color=settings.color_default)
        buf = await render_research_card(pts, cost, frac, self._hunt_ready)
        file = discord.File(buf, filename="research.png") if buf else None
        if file:
            emb.set_image(url="attachment://research.png")
        if reduced:
            pct = int(settings.research_reduced_factor * 100)
            linha_dia = (f"📅 Você já pesquisou bastante hoje — ganhos **reduzidos "
                         f"(~{pct}%)**. Reseta amanhã.")
        else:
            linha_dia = (f"📅 Mais **{until_reduced}** de pesquisa a valor cheio hoje; "
                         f"depois disso os ganhos caem.")
        linhas = [
            f"🔎 Explorar **+{settings.rp_explore}** · 🎯 Capturar **+{settings.rp_capture}** · "
            f"⚔️ Vencer **+{settings.rp_battle_win}** · 📋 Missão **+{settings.rp_quest}**",
            linha_dia,
            f"🏆 Caçadas concluídas: **{hunts}**",
        ]
        if self._hunt_ready:
            linhas.append("⚔️ **Caçada Lendária liberada!** Vença o lendário para capturá-lo.")
        if myth_ok:
            estado = " — **pronta!**" if self._mythic_ready else ""
            linhas.append(f"🌈 Caçada Mítica: **{myth_pts:,}/{myth_cost:,}**{estado}")
        emb.description = "\n".join(linhas)
        emb.set_footer(text="Lendários/míticos vêm só pela Caçada (o explore não sorteia mais).")
        return emb, file

    async def do_hunt(self, interaction, kind: str):
        from bot.utils.research import hunt_cost, mythic_cost
        from bot.utils.rarity import pick_species_of_rarity
        from bot.cogs.battle import BattleView, build_wild_mon
        battle_cog = self.ctx.bot.get_cog("Batalha")
        if battle_cog is None:
            self.flash = "Batalha indisponível."
            self.goto("pesquisa")
            return await self.show(interaction)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            cost = mythic_cost() if kind == "mythical" else hunt_cost(user)
            if (user.research_points or 0) < cost:
                self.flash = "Você ainda não tem pontos suficientes para essa Caçada."
                self.goto("pesquisa")
                return await self.show(interaction)
        species = pick_species_of_rarity({"mythical"} if kind == "mythical" else {"legendary"})
        if species is None:
            self.flash = "Nenhum alvo disponível para a Caçada."
            self.goto("pesquisa")
            return await self.show(interaction)
        p1_team, err = await battle_cog.load_team(self.ctx, self.ctx.author)
        if not p1_team:
            self.flash = f"⚠️ {err}"
            self.goto("pesquisa")
            return await self.show(interaction)
        target_level = min(100, max(p1_team[0].level + 5, 50))
        leg = build_wild_mon(species, target_level, name=species.name, perfect_iv=True)
        pid = self.author_id

        async def on_finish(winner, loser):
            if winner.owner_id == pid:
                await self._grant_hunt(species, target_level, cost)

        self.handed_off = True
        bview = BattleView(battle_cog, self.ctx, p1_team, [leg], pid, None,
                           on_finish=on_finish, opponent_name=species.name,
                           end_view=PostBattleView(self, "pesquisa"))
        bview.message = self.message
        await bview.start_hosted(interaction)

    async def _grant_hunt(self, species, level, cost):
        """Ao VENCER a Caçada: cobra o RP, conta a caçada e captura o lendário."""
        from bot.cogs.explore import do_capture
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            if (user.research_points or 0) < cost:
                self.flash = "Pontos insuficientes — a Caçada foi cancelada."
                return
            user.research_points -= cost
            user.hunts_won = (user.hunts_won or 0) + 1
        idx, coins, new_dex, newly, iv_pct = await do_capture(
            self.ctx.bot, self.author_id, species, level, False, iv_rolls=4, iv_floor=25)
        extra = f"IV {iv_pct:.1f}% · +{coins}🪙 · #{idx}"
        if new_dex:
            extra += "\n📕 Novo registro na Pokédex!"
        self.flash = f"🎉 Você caçou e capturou **{species.name}**!\n{extra}"
        try:
            await self.ctx.bot.announce_rare(self.ctx.guild, self.ctx.author, species, False, level)
        except Exception:  # noqa: BLE001
            pass

    async def _s_detalhe(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            if poke is None:
                self.goto("colecao")
                return await self._s_colecao()
            sp = POKEDEX.get(poke.species_id)
            inv = await helpers.get_inventory(session, user.id)
            evo_title, evo_text = _evo_info(sp, poke.level, inv)
            # cartão completo (atributos, IVs, natureza, golpes) reaproveitando o info_embed
            emb = embeds.info_embed(sp, poke)
            emb.add_field(name=evo_title, value=evo_text, inline=False)
        return emb, None

    async def _s_evolve_choice(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            sp = POKEDEX.get(poke.species_id) if poke else None
            inv = await helpers.get_inventory(session, user.id) if poke else {}
            options = available_evos(sp, poke.level, inv) if sp else []
            self._opts = [discord.SelectOption(label=o["name"], value=str(o["to"])) for o in options]
            nome = sp.name if sp else "?"
            linhas = [f"✨ **{o['name']}**" + (f" — {o['item'].emoji} {o['item'].name}" if o["stone"] else " — por nível")
                      for o in options]
        emb = discord.Embed(
            title="🔀 Escolha a evolução",
            description=(f"**{nome}** pode seguir **{len(linhas)} caminhos**:\n" + "\n".join(linhas)
                        + "\n\nEscolha abaixo. Evoluções por pedra **consomem** a pedra. 🪨"),
            color=settings.color_info)
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
                                        f"Seu saldo: **{coins:,}** 🪙\n\n"
                                        f"Clique em **🛒 Comprar** e **digite a quantidade** que quiser."),
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

    async def _s_market_sell(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            listed = set(await session.scalars(select(MarketListing.pokemon_id).where(
                MarketListing.seller_id == user.id, MarketListing.active == True)))  # noqa: E712
            mons = await helpers.list_pokemon(session, user.id)
        # todos os elegíveis (não-favoritos e não-anunciados), com paginação de 25
        elegiveis = [(m, sp) for m in mons if not m.favorite and m.id not in listed
                     and (sp := POKEDEX.get(m.species_id))]
        self._opts = []
        if not elegiveis:
            return discord.Embed(title="📢 Anunciar no mercado", color=settings.color_info,
                                 description="Nenhum pokémon disponível para anunciar."), None
        pages = max(1, (len(elegiveis) + 24) // 25)
        self.page %= pages
        for m, sp in elegiveis[self.page * 25:(self.page + 1) * 25]:
            self._opts.append(discord.SelectOption(
                label=f"#{m.idx} {sp.name}"[:100],
                description=f"Nv {m.level} · IV {m.iv_percent:.0f}%", value=str(m.idx)))
        emb = discord.Embed(title=f"📢 Anunciar no mercado — pág {self.page + 1}/{pages}",
                            description="Escolha o pokémon. Depois você digita o **preço**.\n"
                                        "🔒 Favoritos e já anunciados não aparecem.",
                            color=settings.color_info)
        return emb, None

    async def _s_mochila(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            inv = await helpers.get_inventory(session, user.id)
        grouped, self._opts = {}, []
        for key, qty in sorted(inv.items()):
            it = get_item(key)
            if it is None or qty <= 0:
                continue
            grouped.setdefault(it.category, []).append(f"{it.emoji} **{it.name}** ×{qty}")
            if it.category in ("stone", "booster", "lure"):
                self._opts.append(discord.SelectOption(
                    label=f"{it.name} ×{qty}"[:100], description=it.description[:100],
                    value=it.key, emoji=it.emoji))
        labels = {"ball": "🎯 Pokébolas", "stone": "💎 Pedras", "lure": "🪔 Incensos",
                  "booster": "📈 Boosters", "misc": "📦 Outros"}
        emb = discord.Embed(title="🎒 Mochila", color=settings.color_info)
        if not grouped:
            emb.description = "Vazia! Compre itens na 🛒 Loja."
            return emb, None
        for cat, label in labels.items():
            if cat in grouped:
                emb.add_field(name=label, value="\n".join(grouped[cat]), inline=False)
        emb.set_footer(text="Escolha um item no menu para usar.")
        return emb, None

    async def _s_use_target(self):
        it = get_item(self.use_item_key)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            mons = await helpers.list_pokemon(session, user.id)
        rows = [(m, POKEDEX.get(m.species_id)) for m in mons]
        rows = [(m, sp) for m, sp in rows if sp]
        pages = max(1, (len(rows) + 24) // 25)
        self.page %= pages
        self._opts = [discord.SelectOption(
            label=f"{'❤️ ' if m.favorite else ''}#{m.idx} {sp.name}"[:100],
            description=f"Nv {m.level} · IV {m.iv_percent:.0f}% · {getattr(m, 'nature', '')}"[:100],
            value=str(m.idx)) for m, sp in rows[self.page * 25:(self.page + 1) * 25]]
        emb = discord.Embed(title=f"{it.emoji if it else '🎒'} Usar {it.name if it else 'item'}",
                            description=f"Em qual pokémon? — pág {self.page + 1}/{pages}",
                            color=settings.color_info)
        return emb, None

    async def _s_ranking(self):
        from bot.cogs.progression import LEADERBOARD_TYPES
        col, title, unit = LEADERBOARD_TYPES.get(self.rank_type, LEADERBOARD_TYPES["caught"])
        column = getattr(User, col)
        async with session_scope() as session:
            # coalesce: trata NULL como 0 p/ os antigos (senão NULLS FIRST no Postgres
            # empurraria quem realmente pontuou p/ fora do top 10)
            res = await session.scalars(
                select(User).order_by(func.coalesce(column, 0).desc()).limit(10))
            users = list(res)
        medals = ["🥇", "🥈", "🥉"] + ["🔹"] * 7
        linhas = []
        for i, u in enumerate(users):
            val = getattr(u, col) or 0   # badge_count etc. podem ser NULL no banco
            if val == 0 and self.rank_type != "level":
                continue
            linhas.append(f"{medals[i]} <@{u.discord_id}> — **{val:,}** {unit}")
        vazio = {
            "badges": "Ninguém conquistou insígnias ainda — vença líderes na 🏆 Liga para liderar!",
            "shiny": "Nenhum shiny capturado ainda. ✨",
            "battles": "Nenhuma vitória registrada ainda. ⚔️",
        }.get(self.rank_type, "Ninguém no ranking ainda.")
        emb = discord.Embed(title=f"📊 {title}", color=settings.color_info,
                            description="\n".join(linhas) or vazio)
        emb.set_footer(text="Troque a categoria nos botões abaixo.")
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
        linhas, self._opts = [], []
        for i, c in enumerate(CHALLENGES):
            unlocked = i == 0 or CHALLENGES[i - 1].key in badges
            st = "✅" if c.key in badges else ("▶️" if unlocked else "🔒")
            tag = {"champion": "👑 ", "elite": "⭐ ", "legend": "🌟 ", "myth": "💠 "}.get(c.kind, "")
            linhas.append(f"{st} `{i + 1:>2}` {c.emoji} {tag}**{c.name}** — {c.leader}")
            if unlocked and len(self._opts) < 25:
                est = "🔁 revanche" if c.key in badges else "▶️ disponível"
                self._opts.append(discord.SelectOption(
                    label=f"{i + 1}. {c.name}"[:100], description=f"{c.leader} · {est}"[:100], value=c.key))
        emb = discord.Embed(title=f"🏆 Liga ({len(badges)}/{len(CHALLENGES)})",
                            description="\n".join(linhas), color=settings.color_default)
        emb.set_footer(text=f"Time: {slots} slots • escolha no menu para DESAFIAR (privado)")
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
        # RP de Pesquisa por explorar (respeita o teto diário)
        from bot.utils.research import grant_rp
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            rp = grant_rp(user, settings.rp_explore)
        rp_txt = f"\n🔬 +{rp} pesquisa" if rp else ""
        from bot.cogs.explore import LOCATIONS
        location = random.choice(LOCATIONS)
        roll = random.random()
        if roll < settings.explore_nothing_chance:
            self.encounter = None
            self.result = ("nothing", f"📍 *{location}*\nNada por aqui... tente de novo.{rp_txt}")
            return await self.show(interaction)
        if roll < settings.explore_nothing_chance + settings.explore_coins_chance:
            coins = random.randint(settings.explore_coins_min, settings.explore_coins_max)
            async with session_scope() as session:
                user = await helpers.fetch_user(session, self.author_id)
                user.coins += coins
            self.encounter = None
            self.result = ("coins", f"📍 *{location}*\nVocê achou **{coins} PokéCoins**! 💰{rp_txt}")
            return await self.show(interaction)
        # encontro (explore NÃO sorteia lendário/mítico — eles vêm pela Caçada)
        species = pick_spawn_species(exclude_rarities={"legendary", "mythical"})
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
                    from bot.utils.research import grant_rp
                    ganhos = []
                    for q, cur, done, claimed in quest_state(user):
                        if done and not claimed and (c := claim_quest(user, q.key)):
                            user.coins += c.reward_coins
                            helpers.grant_trainer_xp(user, c.reward_xp)
                            grant_rp(user, settings.rp_quest)   # RP de Pesquisa por missão
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
                inv = await helpers.get_inventory(session, user.id)
                options = available_evos(sp, poke.level, inv)
                if not options:
                    self.flash = _evo_blocked_msg(sp, poke.level)
                elif len(options) == 1:
                    await self._do_evolve_target(session, user, poke, options[0]["to"])
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

    async def _do_evolve_target(self, session, user, poke, target_to):
        """Evolui para `target_to`, validando nível ou consumindo a pedra necessária."""
        sp = POKEDEX.get(poke.species_id)
        step = next((s for s in sp.evolutions if s.to == target_to), None)
        if step is None:
            self.flash = "Evolução não disponível."
            return
        sit = None
        if step.method == "level":
            if step.level is None or poke.level < step.level:
                self.flash = "Ainda não tem nível para essa evolução."
                return
        elif step.method == "stone":
            sit = _stone_item_for(step)
            inv = await helpers.get_inventory(session, user.id)
            if sit is None or inv.get(sit.key, 0) < 1:
                self.flash = f"Você não tem a pedra necessária ({sit.name if sit else '?'})."
                return
            await helpers.take_item(session, user.id, sit.key, 1)
        else:
            self.flash = "Essa evolução ainda não está disponível."
            return
        before, new = sp.name, POKEDEX.get(target_to)
        poke.species_id = new.id
        await helpers.update_pokedex(session, user.id, new.id, seen=1, caught=1)
        bump_quest(user, "evolve", 1)
        extra = f" usando {sit.name}" if sit else ""
        self.flash = f"✨ {before} evoluiu para **{new.name}**{extra}!"

    async def evolve_to(self, interaction, target_to):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self.detail_idx)
            if poke:
                await self._do_evolve_target(session, user, poke, target_to)
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

    async def do_duel(self, interaction):
        from bot.cogs.battle import BattleView, build_wild_mon, pick_balanced_wild_species
        battle_cog = self.ctx.bot.get_cog("Batalha")
        if battle_cog is None:
            self.flash = "Batalha indisponível."
            return await self.show(interaction)
        p1_team, err = await battle_cog.load_team(self.ctx, self.ctx.author)
        if not p1_team:
            self.flash = f"⚠️ {err}"
            return await self.show(interaction)
        lead = p1_team[0]
        species = pick_balanced_wild_species(lead.species)
        level = max(1, lead.level - random.randint(0, 2))
        p2_team = [build_wild_mon(species, level)]
        # roda a batalha DENTRO da mensagem do /menu (privada). Ao fim, mostra
        # botões "Duelar de novo" / "Menu" (PostBattleView).
        self.handed_off = True
        bview = BattleView(battle_cog, self.ctx, p1_team, p2_team, self.author_id, None,
                           end_view=PostBattleView(self, "duel"))
        bview.message = self.message
        await bview.start_hosted(interaction)

    async def do_gym(self, interaction, key: str):
        """Desafia um líder da Liga DENTRO do /menu (privado). Concede insígnia ao vencer."""
        from bot.cogs.battle import BattleView, build_wild_mon
        from bot.cogs.gyms import REMATCH_CD
        ch = CHALLENGES_BY_KEY.get(key)
        battle_cog = self.ctx.bot.get_cog("Batalha")
        if ch is None or battle_cog is None:
            self.flash = "Desafio indisponível."
            self.goto("liga")
            return await self.show(interaction)
        idx = challenge_index(ch.key)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            badges = list(user.badges or [])
            cooldowns = dict(user.gym_cooldowns or {})
        # trancado?
        if idx > 0 and CHALLENGES[idx - 1].key not in badges:
            self.flash = f"🔒 Vença antes: **{CHALLENGES[idx - 1].name}**."
            self.goto("liga")
            return await self.show(interaction)
        # já venceu e em cooldown?
        if ch.key in badges:
            remaining = REMATCH_CD - (time.time() - cooldowns.get(ch.key, 0))
            if remaining > 0:
                h, m = divmod(int(remaining) // 60, 60)
                self.flash = f"⏳ Revanche de **{ch.name}** em **{h}h {m}min**."
                self.goto("liga")
                return await self.show(interaction)
        p1_team, err = await battle_cog.load_team(self.ctx, self.ctx.author)
        if not p1_team:
            self.flash = f"⚠️ {err}"
            self.goto("liga")
            return await self.show(interaction)
        leader_team = [build_wild_mon(POKEDEX.by_name(n), lv, name=n, perfect_iv=ch.perfect)
                       for n, lv in ch.team]
        already = ch.key in badges
        pid = self.author_id

        async def on_finish(winner, loser):
            await self._grant_gym(ch, winner.owner_id == pid, already)

        self.handed_off = True
        bview = BattleView(battle_cog, self.ctx, p1_team, leader_team, pid, None,
                           on_finish=on_finish, opponent_name=ch.leader,
                           end_view=PostBattleView(self, "liga"))
        bview.message = self.message
        await bview.start_hosted(interaction)

    async def _grant_gym(self, ch, won: bool, already: bool):
        """Concede a recompensa do ginásio e guarda o texto no flash (mostrado na Liga)."""
        from bot.cogs.gyms import REMATCH_CD
        if not won:
            self.flash = f"Você foi derrotado por **{ch.leader}**... treine e volte! 💪"
            return
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            badges = list(user.badges or [])
            if ch.key not in badges:
                before = party_slots(badges)
                badges.append(ch.key)
                user.badges = badges
                user.badge_count = len(badges)
                user.coins += ch.reward_coins
                lines = [f"🎖️ Você ganhou a **{ch.badge}** {ch.emoji}!",
                         f"💰 +{ch.reward_coins:,} PokéCoins"]
                it = get_item(ch.reward_item) if ch.reward_item else None
                if it is not None:
                    await helpers.add_item(session, user.id, it.key, ch.reward_item_qty)
                    lines.append(f"{it.emoji} +{ch.reward_item_qty}× {it.name}")
                after = party_slots(badges)
                if after > before:
                    lines.append(f"📈 Seu time aumentou para **{after} slots**!")
                if ch.kind == "champion":
                    lines.append("👑 **VOCÊ É O CAMPEÃO DA LIGA!** 🏆")
                elif ch.kind == "myth":
                    lines.append("💠 **VOCÊ DOMINOU A CÂMARA DOS MÍTICOS!** 🌌")
                elif ch.kind == "legend":
                    lines.append("🌟 Um covil lendário tombou diante de você!")
                cds = dict(user.gym_cooldowns or {})
                cds[ch.key] = time.time()
                user.gym_cooldowns = cds
                self.flash = "\n".join(lines)
            else:
                cds = dict(user.gym_cooldowns or {})
                now, last = time.time(), cds.get(ch.key, 0)
                if now - last >= REMATCH_CD:
                    reward = max(1, ch.reward_coins // 4)
                    user.coins += reward
                    cds[ch.key] = now
                    user.gym_cooldowns = cds
                    self.flash = f"🔁 Revanche vencida! +{reward:,} PokéCoins."
                else:
                    self.flash = "Você já venceu este líder hoje (revanche em cooldown)."

    async def open_price_modal(self, interaction, idx: int):
        await interaction.response.send_modal(PriceModal(self, idx))

    async def refresh_from_modal(self, interaction):
        """Atualiza a mensagem do hub após um Modal (que não está ligado a ela)."""
        await interaction.response.defer()
        emb, file = await self.render()
        self._build()
        if self.message is not None:
            await self.message.edit(embed=emb, view=self, attachments=([file] if file else []))

    async def open_detail(self, interaction, idx: int):
        self.detail_idx = idx
        self.goto("detalhe")
        await self.show(interaction)

    async def open_dex_detail(self, interaction, species_id: int):
        self.dex_species_id = species_id
        self.goto("pokedex_detail")
        await self.show(interaction)

    async def set_col_filter(self, interaction, value: str):
        if value.startswith("type:"):
            self.col_filter, self.col_type = "type", value.split(":", 1)[1]
        else:
            self.col_filter, self.col_type = value, None
        self.goto("colecao")
        await self.show(interaction)

    async def open_shop_item(self, interaction, key: str):
        self.shop_key = key
        self.goto("loja_buy")
        await self.show(interaction)

    async def open_use_item(self, interaction, key: str):
        it = get_item(key)
        if it is None:
            self.flash = "Item inválido."
            self.goto("mochila")
            return await self.show(interaction)
        if it.category == "lure":
            async with session_scope() as session:
                user = await helpers.fetch_user(session, self.author_id)
                ok = await helpers.take_item(session, user.id, it.key, 1)
            if ok:
                spawn = self.ctx.bot.get_cog("Spawn")
                if spawn is not None:
                    spawn.add_lure(self.ctx.channel.id, it.lure_minutes)
                self.flash = f"🪔 Incenso ativado por **{it.lure_minutes} min** neste canal!"
            else:
                self.flash = "Você não tem esse item."
            self.goto("mochila")
            return await self.show(interaction)
        self.use_item_key = key
        self.goto("use_target")
        await self.show(interaction)

    async def use_item_on(self, interaction, idx: int):
        it = get_item(self.use_item_key)
        # boosters (rare candy, xp, cristal de IV): pergunta a QUANTIDADE num modal
        if it is not None and it.category == "booster":
            return await interaction.response.send_modal(UseQtyModal(self, idx, it))
        # pedras e demais: aplica 1 (pedra evolui uma vez)
        await self._apply_item(idx, 1)
        self.goto("mochila")
        await self.show(interaction)

    async def use_item_qty_from_modal(self, interaction, idx: int, qty: int):
        await self._apply_item(idx, qty)
        self.goto("mochila")
        await self.refresh_from_modal(interaction)

    async def _apply_item(self, idx: int, qty: int) -> None:
        """Aplica o item atual `qty` vezes ao pokémon `idx` (pedra sempre 1). Só seta o flash."""
        it = get_item(self.use_item_key)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            inv = await helpers.get_inventory(session, user.id)
            have = inv.get(it.key, 0) if it else 0
            if it is None or have < 1:
                self.flash = "Você não tem mais esse item."
                return
            poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
            if poke is None:
                self.flash = "Pokémon não é seu."
                return
            sp = POKEDEX.get(poke.species_id)
            if it.category == "stone":
                step = sp.can_evolve_by_stone(it.stone)
                if step is None:
                    self.flash = f"❌ {sp.name} não evolui com {it.name}."
                else:
                    new = POKEDEX.get(step.to)
                    poke.species_id = new.id
                    await helpers.update_pokedex(session, user.id, new.id, seen=1, caught=1)
                    await helpers.take_item(session, user.id, it.key, 1)
                    bump_quest(user, "evolve", 1)
                    self.flash = f"✨ {sp.name} evoluiu para **{new.name}** com {it.name}!"
                return
            if it.category != "booster":
                self.flash = "Esse item não pode ser usado assim."
                return
            n = max(1, min(qty, have))   # nunca usa mais do que tem
            if it.level_amount:
                falta = (100 - poke.level) // it.level_amount  # quantos ainda sobem nível
                if falta <= 0:
                    self.flash = f"{sp.name} já está no **nível máximo** (100)."
                    return
                n = min(n, falta)
                before = poke.level
                poke.level = min(100, poke.level + n * it.level_amount)
                await helpers.take_item(session, user.id, it.key, n)
                self.flash = f"⬆️ {sp.name}: Nv {before} → **{poke.level}** (usou {n}× {it.name})."
            elif it.iv_boost:
                before = poke.iv_percent
                for attr in ("iv_hp", "iv_atk", "iv_def", "iv_spa", "iv_spd", "iv_spe"):
                    setattr(poke, attr, min(31, getattr(poke, attr) + n * it.iv_boost))
                await helpers.take_item(session, user.id, it.key, n)
                self.flash = f"💠 IV de {sp.name}: {before:.1f}% → **{poke.iv_percent:.1f}%** (usou {n}× {it.name})."
            elif it.xp_amount:
                nl, nx, g = apply_xp(poke.level, poke.xp, n * it.xp_amount)
                poke.level, poke.xp = nl, nx
                await helpers.take_item(session, user.id, it.key, n)
                self.flash = (f"⭐ {sp.name} +{n * it.xp_amount:,} XP"
                              + (f" (subiu {g} nível(is)!)" if g else "") + f" (usou {n}× {it.name}).")
            else:
                self.flash = "Esse item não pode ser usado assim."

    async def _do_buy(self, qty: int) -> None:
        """Efetiva a compra de `qty` do item atual e prepara o flash (sem render)."""
        it = get_item(self.shop_key)
        custo = it.price * qty
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            if user.coins < custo:
                self.flash = f"Saldo insuficiente: {qty}× {it.name} custa **{custo:,}** 🪙."
            else:
                user.coins -= custo
                nova = await helpers.add_item(session, user.id, it.key, qty)
                self.flash = f"🛒 Comprou **{qty}× {it.name}** por {custo:,} 🪙. (tem {nova})"

    async def buy_item(self, interaction, qty: int):
        await self._do_buy(qty)
        await self.show(interaction)

    async def buy_item_from_modal(self, interaction, qty: int):
        await self._do_buy(qty)
        await self.refresh_from_modal(interaction)

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
        await self.ctx.bot.announce_rare(self.ctx.guild, self.ctx.author, sp, shiny, level)

    async def _explore_battle(self, interaction):
        from bot.cogs.battle import BattleView, build_wild_mon
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
        enc_copy = dict(enc)   # preserva p/ poder VOLTAR à escolha do encontro
        self.encounter = None
        p2_team = [build_wild_mon(sp, level, shiny=shiny)]

        async def on_back(inter):
            # "Voltar": cancela a batalha e restaura o encontro (capturar/batalhar/ignorar)
            self.handed_off = False
            self.encounter = {**enc_copy, "phase": "main"}
            self.result = None
            self.goto("explorar")
            await self.show(inter)

        # batalha privada na própria mensagem; ao fim: "Explorar de novo" / "Menu"
        self.handed_off = True
        bview = BattleView(battle_cog, self.ctx, p1_team, p2_team, self.author_id, None,
                           end_view=PostBattleView(self, "explore"), on_back=on_back)
        bview.message = self.message
        await bview.start_hosted(interaction)


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
        if self._action == "duel":
            return await self._hub.do_duel(interaction)
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
    def __init__(self, view, to, label, row=0):
        super().__init__(label=label, emoji="✨", style=discord.ButtonStyle.success, row=row)
        self._hub, self._to = view, to

    async def callback(self, interaction):
        await self._hub.evolve_to(interaction, self._to)


class HuntBtn(discord.ui.Button):
    def __init__(self, view, kind, label, emoji):
        super().__init__(label=label, emoji=emoji, style=discord.ButtonStyle.success, row=0)
        self._hub, self._kind = view, kind

    async def callback(self, interaction):
        await self._hub.do_hunt(interaction, self._kind)


class BuyQtyBtn(discord.ui.Button):
    def __init__(self, view):
        super().__init__(label="Comprar", emoji="🛒", style=discord.ButtonStyle.success, row=0)
        self._hub = view

    async def callback(self, interaction):
        await interaction.response.send_modal(BuyQtyModal(self._hub))


class BuyQtyModal(discord.ui.Modal, title="🛒 Comprar item"):
    qtd = discord.ui.TextInput(label="Quantidade", placeholder="Ex.: 7",
                               min_length=1, max_length=7)

    def __init__(self, hub: "HubView"):
        super().__init__()
        self._hub = hub

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.qtd.value).strip().replace(".", "").replace(",", "")
        if not raw.isdigit() or not (1 <= int(raw) <= 1_000_000):
            await interaction.response.send_message(
                "Quantidade inválida (use só números, 1–1.000.000).", ephemeral=True)
            return
        await self._hub.buy_item_from_modal(interaction, int(raw))


class UseQtyModal(discord.ui.Modal):
    qtd = discord.ui.TextInput(label="Quantos usar?", placeholder="Ex.: 10",
                               min_length=1, max_length=7)

    def __init__(self, hub: "HubView", idx: int, item):
        super().__init__(title=f"Usar {item.name}"[:45])
        self._hub, self._idx = hub, idx

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.qtd.value).strip().replace(".", "").replace(",", "")
        if not raw.isdigit() or not (1 <= int(raw) <= 1_000_000):
            await interaction.response.send_message(
                "Quantidade inválida (use só números, 1–1.000.000).", ephemeral=True)
            return
        await self._hub.use_item_qty_from_modal(interaction, self._idx, int(raw))


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
        elif self._kind == "sell":
            await self._hub.open_price_modal(interaction, int(v))
        elif self._kind == "gym":
            await self._hub.do_gym(interaction, v)
        elif self._kind == "useitem":
            await self._hub.open_use_item(interaction, v)
        elif self._kind == "usetarget":
            await self._hub.use_item_on(interaction, int(v))
        elif self._kind == "dexview":
            await self._hub.open_dex_detail(interaction, int(v))


class FilterBtn(discord.ui.Button):
    def __init__(self, view, label, row):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=row)
        self._hub = view

    async def callback(self, interaction):
        self._hub.goto("colecao_filtro")
        await self._hub.show(interaction)


class FilterChoiceSelect(discord.ui.Select):
    def __init__(self, view):
        super().__init__(placeholder="Filtrar por...", options=view._opts[:25], row=0)
        self._hub = view

    async def callback(self, interaction):
        await self._hub.set_col_filter(interaction, self.values[0])


class RankBtn(discord.ui.Button):
    _LABELS = {"caught": "Capturas", "shiny": "Shinies", "coins": "Moedas",
               "battles": "Vitórias", "level": "Nível", "badges": "Insígnias"}

    def __init__(self, view, rtype, emoji, row):
        super().__init__(label=self._LABELS.get(rtype, rtype), emoji=emoji,
                         style=discord.ButtonStyle.secondary, row=row)
        self._hub, self._rtype = view, rtype

    async def callback(self, interaction):
        self._hub.rank_type = self._rtype
        self._hub.goto("ranking")
        await self._hub.show(interaction)


class PostBattleView(discord.ui.View):
    """Botões mostrados ao fim de uma batalha privada do hub (na mesma mensagem)."""

    def __init__(self, hub: "HubView", mode: str):
        super().__init__(timeout=180)
        self.hub = hub
        self.message = hub.message
        again = {
            "duel": ("duel_again", "Duelar de novo", "⚔️"),
            "explore": ("explore_again", "Explorar de novo", "🌿"),
            "liga": ("liga", "Ver Liga", "🏆"),
            "pesquisa": ("pesquisa", "Ver Pesquisa", "🔬"),
        }.get(mode, ("menu", "Menu", "🏠"))
        self.add_item(PostBtn(hub, again[0], again[1], again[2], discord.ButtonStyle.success))
        self.add_item(PostBtn(hub, "menu", "Menu", "🏠", discord.ButtonStyle.secondary))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.hub.author_id:
            await interaction.response.send_message("Esse painel não é seu. 😉", ephemeral=True)
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


class PostBtn(discord.ui.Button):
    def __init__(self, hub, action, label, emoji, style):
        super().__init__(label=label, emoji=emoji, style=style)
        self._hub, self._action = hub, action

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view is not None:
            self.view.stop()  # encerra esta View (evita o timeout atropelar o que vem)
        fresh = HubView(self._hub.ctx)      # hub novo e "vivo" para navegar
        fresh.message = self._hub.message
        fresh.flash = self._hub.flash       # carrega aviso (ex.: recompensa do ginásio)
        fresh._register_active()            # continua a mesma sessão (1 menu por usuário)
        if self._action == "duel_again":
            await fresh.do_duel(interaction)
        elif self._action == "explore_again":
            await fresh.do_explore(interaction)
        elif self._action == "liga":
            fresh.goto("liga")
            await fresh.show(interaction)
        elif self._action == "pesquisa":
            fresh.goto("pesquisa")
            await fresh.show(interaction)
        else:  # menu
            fresh.goto("home")
            await fresh.show(interaction)


class PriceModal(discord.ui.Modal, title="📢 Anunciar no mercado"):
    preco = discord.ui.TextInput(label="Preço em PokéCoins", placeholder="Ex.: 1500",
                                 min_length=1, max_length=9)

    def __init__(self, hub: "HubView", idx: int):
        super().__init__()
        self._hub, self._idx = hub, idx

    async def on_submit(self, interaction: discord.Interaction) -> None:
        raw = str(self.preco.value).strip().replace(".", "").replace(",", "")
        if not raw.isdigit() or not (1 <= int(raw) <= 100_000_000):
            await interaction.response.send_message(
                "Preço inválido (use só números, 1–100.000.000).", ephemeral=True)
            return
        price = int(raw)
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self._hub.author_id)
            poke = await helpers.get_pokemon_by_idx(session, user.id, self._idx)
            if poke is None:
                self._hub.flash = "Pokémon não é seu."
            elif poke.favorite:
                self._hub.flash = "Favorito protegido. Desfavorite antes de anunciar."
            else:
                existing = await session.scalar(select(MarketListing).where(
                    MarketListing.pokemon_id == poke.id, MarketListing.active == True))  # noqa: E712
                if existing:
                    self._hub.flash = "Esse pokémon já está anunciado."
                else:
                    if user.selected_id == poke.id:
                        user.selected_id = None
                    user.party = [p for p in (user.party or []) if p != poke.idx]
                    lst = MarketListing(seller_id=user.id, pokemon_id=poke.id, price=price)
                    session.add(lst)
                    await session.flush()
                    self._hub.flash = (f"🏪 **{POKEDEX.get(poke.species_id).name}** anunciado por "
                                       f"**{price:,}** 🪙 (ID {lst.id}).")
        self._hub.goto("market")
        await self._hub.refresh_from_modal(interaction)


class CloseBtn(discord.ui.Button):
    def __init__(self, view, row=2):
        super().__init__(label="Fechar", emoji="❌", style=discord.ButtonStyle.danger, row=row)
        self._hub = view

    async def callback(self, interaction):
        for c in self._hub.children:
            c.disabled = True
        await interaction.response.edit_message(
            content="Painel fechado. Abra de novo com `/menu`. 👋", embed=None, view=self._hub, attachments=[])
        self._hub._deregister_active()
        self._hub.stop()


# ==========================================================================
class Hub(commands.Cog, name="Painel"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="menu", aliases=["jogar", "hub", "painel"])
    @commands.guild_only()
    async def menu(self, ctx: commands.Context) -> None:
        """Abre o painel central do jogo (use /menu para o modo privado, só você vê)."""
        # 1 painel por usuário: ter vários abertos zeraria o cooldown de explorar
        # em cada um (burlando a espera). Se já houver um aberto, recusa.
        if HubView.active_session(ctx.author.id) is not None:
            aviso = ("⚠️ Você já tem um **/menu aberto**! Use o painel que já está aberto "
                     "(ou feche-o com ❌ Fechar) antes de abrir outro.")
            if ctx.interaction is not None:
                await ctx.interaction.response.send_message(aviso, ephemeral=True)
            else:
                await ctx.send(aviso)
            return
        view = HubView(ctx)
        view._register_active()   # antes de qualquer await: fecha a janela de corrida
        try:
            emb, file = await view.render()
            view._build()
            if ctx.interaction is not None:
                # slash: SEMPRE ephemeral (só o jogador vê) — usa a API da interação direto
                kwargs = {"embed": emb, "view": view, "ephemeral": True}
                if file:
                    kwargs["file"] = file
                await ctx.interaction.response.send_message(**kwargs)
                view.message = await ctx.interaction.original_response()
            else:
                kwargs = {"embed": emb, "view": view}
                if file:
                    kwargs["file"] = file
                view.message = await ctx.send(**kwargs)
        except Exception:
            view._deregister_active()   # falhou ao abrir: não deixa o usuário travado
            raise

    @commands.hybrid_command(name="fechar", aliases=["close", "sair"])
    @commands.guild_only()
    async def fechar(self, ctx: commands.Context) -> None:
        """Fecha o seu /menu aberto (libera para abrir um novo)."""
        view = HubView.active_session(ctx.author.id)
        if view is None:
            aviso = "Você não tem nenhum **/menu** aberto."
        else:
            view._deregister_active()
            for c in view.children:
                c.disabled = True
            try:
                if view.message is not None:
                    await view.message.edit(content="Painel fechado. 👋", embed=None,
                                            view=view, attachments=[])
            except discord.HTTPException:
                pass
            view.stop()
            aviso = "✅ Seu **/menu** foi fechado. Você já pode abrir um novo."
        if ctx.interaction is not None:
            await ctx.interaction.response.send_message(aviso, ephemeral=True)
        else:
            await ctx.send(aviso)

    @commands.command(name="sync")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context) -> None:
        """(Dono) Sincroniza os comandos de barra (/) neste servidor."""
        self.bot.tree.copy_global_to(guild=ctx.guild)
        synced = await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ {len(synced)} comando(s) de barra sincronizados aqui.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Hub(bot))
