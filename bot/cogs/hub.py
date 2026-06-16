"""Hub central (p!menu / /menu): um painel com botões que se edita no lugar.

Fase 1: telas de leitura + resgates (Home, Perfil, Time, Coleção, Missões,
Liga, Loja). Explorar e Batalha entram na fase 2.

Aberto por slash (`/menu`) = resposta **ephemeral** (só o jogador vê) ou por
prefixo (`p!menu`) = público. O estado mora no banco; o hub é só a janela.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import discord
from discord.ext import commands
from sqlalchemy import func, select

from config import settings
from bot.data.gyms import CHALLENGES, CHALLENGES_BY_KEY, party_slots
from bot.data.items import ITEMS, SHOP_ORDER
from bot.data.pokemon_data import POKEDEX
from bot.database.db import session_scope
from bot.database.models import PokedexEntry
from bot.utils import embeds, helpers
from bot.utils.images import render_grid
from bot.utils.progression import ACHIEVEMENTS, claim_quest, quest_state
from bot.utils.team_scene import render_team

PER_PAGE_DEX = 9
PER_PAGE_SHOP = 6


# --------------------------------------------------------------------------
#  Lógica de diário (espelha a do cog Economia, para resgatar dentro do hub)
# --------------------------------------------------------------------------
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
    return True, f"🎁 +**{total:,}** PokéCoins! 🔥 Streak: **{user.daily_streak}** (bônus +{bonus:,})."


# ==========================================================================
#  VIEW DO HUB
# ==========================================================================
class HubView(discord.ui.View):
    def __init__(self, author_id: int, prefix: str):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.prefix = prefix
        self.screen = "home"
        self.page = 0
        self.flash = ""          # mensagem temporária (ex.: resultado de resgate)
        self.message: discord.Message | None = None
        self._build()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Abra o seu próprio painel com `/menu`. 😉", ephemeral=True)
            return False
        return True

    # ---- navegação ----
    def goto(self, screen: str) -> None:
        self.screen = screen
        self.page = 0
        self.flash = ""

    def _build(self) -> None:
        self.clear_items()
        if self.screen == "home":
            self.add_item(NavBtn(self, "explorar", "Explorar", "🌿", discord.ButtonStyle.success, 0))
            self.add_item(NavBtn(self, "time", "Time", "🎒", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "colecao", "Coleção", "📦", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "loja", "Loja", "🛒", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "liga", "Liga", "🏆", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "missoes", "Missões", "📋", discord.ButtonStyle.primary, 1))
            self.add_item(NavBtn(self, "perfil", "Perfil", "👤", discord.ButtonStyle.primary, 1))
            self.add_item(CloseBtn(self, row=1))
        elif self.screen in ("colecao", "loja"):
            self.add_item(PageBtn(self, -1, "◀️"))
            self.add_item(PageBtn(self, +1, "▶️"))
            self.add_item(NavBtn(self, "home", "Início", "🏠", discord.ButtonStyle.secondary, 0))
        elif self.screen == "missoes":
            self.add_item(ActionBtn(self, "daily", "Resgatar diário", "🎁", discord.ButtonStyle.success))
            self.add_item(ActionBtn(self, "quests", "Resgatar missões", "📋", discord.ButtonStyle.success))
            self.add_item(NavBtn(self, "home", "Início", "🏠", discord.ButtonStyle.secondary, 0))
        elif self.screen == "liga":
            self.add_item(NavBtn(self, "liga_badges", "Insígnias", "🎖️", discord.ButtonStyle.primary, 0))
            self.add_item(NavBtn(self, "home", "Início", "🏠", discord.ButtonStyle.secondary, 0))
        else:
            back = "liga" if self.screen == "liga_badges" else "home"
            label = "Voltar" if back == "liga" else "Início"
            self.add_item(NavBtn(self, back, label, "◀️" if back == "liga" else "🏠",
                                 discord.ButtonStyle.secondary, 0))

    # ---- render principal ----
    async def render(self) -> tuple[discord.Embed, discord.File | None]:
        builder = {
            "home": self._home, "perfil": self._perfil, "time": self._time,
            "colecao": self._colecao, "missoes": self._missoes, "liga": self._liga,
            "liga_badges": self._liga_badges, "loja": self._loja,
            "explorar": self._explorar_placeholder,
        }.get(self.screen, self._home)
        emb, file = await builder()
        if self.flash:
            emb.add_field(name="✅", value=self.flash, inline=False)
        return emb, file

    async def show(self, interaction: discord.Interaction) -> None:
        self._build()
        emb, file = await self.render()
        await interaction.response.edit_message(
            embed=emb, view=self, attachments=([file] if file else []))

    async def send_first(self, ctx: commands.Context, ephemeral: bool) -> None:
        emb, file = await self.render()
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

    # ==================================================================
    #  TELAS
    # ==================================================================
    async def _home(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            total = await helpers.pokemon_count(session, user.id)
            dex = await session.scalar(
                select(func.count(PokedexEntry.id)).where(
                    PokedexEntry.user_id == user.id, PokedexEntry.caught > 0)) or 0
            sel = await helpers.get_selected(session, user)
            lider = POKEDEX.get(sel.species_id).name if sel else "—"
            coins, badges, slots = user.coins, user.badge_count, party_slots(user.badges)
        emb = discord.Embed(
            title="🎮 Central PokeM1D",
            description=(f"💰 **{coins:,}** PokéCoins\n"
                        f"🎒 Time **{slots} slots**  ·  ⭐ Líder: **{lider}**\n"
                        f"📦 Coleção: **{total}**  ·  📕 Pokédex: **{dex}/{POKEDEX.count()}**\n"
                        f"🏅 Insígnias: **{badges}**\n\n"
                        f"Escolha uma opção abaixo. 👇"),
            color=settings.color_default,
        )
        emb.set_thumbnail(url=settings.sprite_animated(sel.species_id) if sel else settings.sprite_animated(25))
        emb.set_footer(text="Painel pessoal — só você vê (se aberto por /menu).")
        return emb, None

    async def _perfil(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            total = await helpers.pokemon_count(session, user.id)
            dex = await session.scalar(
                select(func.count(PokedexEntry.id)).where(
                    PokedexEntry.user_id == user.id, PokedexEntry.caught > 0)) or 0
            d = dict(level=user.trainer_level, xp=user.trainer_xp, nxt=user.xp_to_next,
                     coins=user.coins, caught=user.total_caught, shiny=user.total_shiny,
                     bw=user.battles_won, bt=user.battles_total, ach=len(user.achievements or []),
                     streak=user.daily_streak, badges=user.badge_count)
        wr = (d["bw"] / d["bt"] * 100) if d["bt"] else 0
        emb = discord.Embed(title="👤 Perfil de treinador", color=settings.color_default)
        emb.add_field(name="Nível", value=f"{d['level']} ({d['xp']}/{d['nxt']} XP)", inline=True)
        emb.add_field(name="PokéCoins", value=f"{d['coins']:,}", inline=True)
        emb.add_field(name="Streak", value=f"🔥 {d['streak']}", inline=True)
        emb.add_field(name="Capturas", value=f"{d['caught']:,}", inline=True)
        emb.add_field(name="Shinies", value=f"✨ {d['shiny']}", inline=True)
        emb.add_field(name="Coleção", value=f"{total}", inline=True)
        emb.add_field(name="Pokédex", value=f"{dex}/{POKEDEX.count()}", inline=True)
        emb.add_field(name="Batalhas", value=f"{d['bw']}V ({wr:.0f}%)", inline=True)
        emb.add_field(name="Insígnias", value=f"🏅 {d['badges']}", inline=True)
        emb.add_field(name="Conquistas", value=f"🏆 {d['ach']}/{len(ACHIEVEMENTS)}", inline=True)
        return emb, None

    async def _time(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            party = list(user.party or [])
            pmax = party_slots(user.badges)
            members = []
            for pos, idx in enumerate(party, 1):
                poke = await helpers.get_pokemon_by_idx(session, user.id, idx)
                if poke:
                    sp = POKEDEX.get(poke.species_id)
                    members.append(dict(species_id=sp.id, shiny=poke.shiny, name=sp.name,
                                        level=poke.level, iv=poke.iv_percent, idx=idx, lead=pos == 1))
        emb = discord.Embed(title=f"🎒 Seu time ({len(members)}/{pmax})", color=settings.color_default)
        if not members:
            emb.description = (f"Seu time está vazio. Monte com `{self.prefix}party add <#>`.\n"
                              f"👑 O 1º é o líder (batalha primeiro e define o nível dos encontros).")
            return emb, None
        buf = await render_team(members)
        file = discord.File(buf, filename="team.png") if buf else None
        if file:
            emb.set_image(url="attachment://team.png")
        emb.description = f"👑 Líder bate primeiro. Use `{self.prefix}select <#>` para trocar."
        return emb, file

    async def _colecao(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            mons = await helpers.list_pokemon(session, user.id)
        rows = [(m, POKEDEX.get(m.species_id)) for m in mons]
        rows = [(m, sp) for m, sp in rows if sp]
        if not rows:
            emb = discord.Embed(title="📦 Coleção", color=settings.color_info,
                                description=f"Vazia! Use `{self.prefix}explore` para achar pokémon.")
            return emb, None
        pages = max(1, (len(rows) + PER_PAGE_DEX - 1) // PER_PAGE_DEX)
        self.page %= pages
        sl = rows[self.page * PER_PAGE_DEX:(self.page + 1) * PER_PAGE_DEX]
        entries = [(sp.id, m.shiny, sp.name, f"#{m.idx} Nv{m.level}") for m, sp in sl]
        emb = discord.Embed(title=f"📦 Sua coleção ({len(rows)})  —  pág {self.page + 1}/{pages}",
                            color=settings.color_info)
        buf = await render_grid(entries, cols=3)
        file = discord.File(buf, filename="dex.png") if buf else None
        if file:
            emb.set_image(url="attachment://dex.png")
        emb.set_footer(text=f"Detalhe de um: {self.prefix}info <#>  •  ✨ dourado = shiny")
        return emb, file

    async def _loja(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            coins = user.coins
        itens = [ITEMS[k] for k in SHOP_ORDER if ITEMS[k].price > 0]
        pages = max(1, (len(itens) + PER_PAGE_SHOP - 1) // PER_PAGE_SHOP)
        self.page %= pages
        sl = itens[self.page * PER_PAGE_SHOP:(self.page + 1) * PER_PAGE_SHOP]
        linhas = [f"{it.emoji} **{it.name}** — `{it.price:,}` 🪙\n   ↳ {it.description}" for it in sl]
        emb = discord.Embed(title=f"🛒 PokéMart — pág {self.page + 1}/{pages}",
                            description="\n".join(linhas), color=settings.color_info)
        emb.set_footer(text=f"Saldo: {coins:,} 🪙  •  comprar: {self.prefix}buy <item> [qtd]")
        return emb, None

    async def _missoes(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            state = quest_state(user)
            last = user.last_daily
            streak = user.daily_streak
        agora = datetime.now(timezone.utc)
        daily_ok = last is None or (last.replace(tzinfo=timezone.utc) if last.tzinfo is None
                                    else last).date() != agora.date()
        linhas = []
        for q, cur, done, claimed in state:
            bar = "✅" if (done and claimed) else ("🎁" if done else "⬜")
            linhas.append(f"{bar} **{q.description}** — {min(cur, q.goal)}/{q.goal}  "
                         f"(+{q.reward_coins}🪙 / +{q.reward_xp}XP)")
        emb = discord.Embed(
            title="📋 Missões & Diário",
            description=(f"🎁 **Diário**: {'pronto para resgatar!' if daily_ok else 'já resgatado hoje'}"
                        f"  ·  🔥 streak {streak}\n\n" + "\n".join(linhas)),
            color=settings.color_default,
        )
        emb.set_footer(text="As missões resetam à meia-noite (UTC).")
        return emb, None

    async def _liga(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            badges = set(user.badges or [])
            slots = party_slots(user.badges)
        linhas = []
        for i, c in enumerate(CHALLENGES):
            st = "✅" if c.key in badges else ("▶️" if (i == 0 or CHALLENGES[i - 1].key in badges) else "🔒")
            tag = {"champion": "👑 ", "elite": "⭐ ", "legend": "🌟 ", "myth": "💠 "}.get(c.kind, "")
            linhas.append(f"{st} `{i + 1:>2}` {c.emoji} {tag}**{c.name}** — {c.leader}")
        emb = discord.Embed(title=f"🏆 Liga Pokémon ({len(badges)}/{len(CHALLENGES)})",
                            description="\n".join(linhas), color=settings.color_default)
        emb.set_footer(text=f"Time: {slots} slots  •  desafie com {self.prefix}gym <nº/nome>")
        return emb, None

    async def _liga_badges(self):
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            blist = list(user.badges or [])
        earned = [CHALLENGES_BY_KEY[k] for k in blist if k in CHALLENGES_BY_KEY]
        if not earned:
            desc = f"Nenhuma insígnia ainda. Comece em `{self.prefix}gym 1`!"
        else:
            desc = "  ".join(c.emoji for c in earned) + "\n\n" + "\n".join(
                f"{c.emoji} **{c.badge}** — {c.name}" for c in earned)
        emb = discord.Embed(title=f"🎖️ Insígnias ({len(earned)}/{len(CHALLENGES)})",
                            description=desc, color=settings.color_default)
        return emb, None

    async def _explorar_placeholder(self):
        emb = discord.Embed(
            title="🌿 Explorar",
            description=(f"A exploração e as batalhas dentro do hub chegam **em breve**!\n\n"
                        f"Por enquanto, use **`{self.prefix}explore`** no canal de jogo. "
                        f"A cena bonita de encontro já está lá. 🌳"),
            color=settings.color_info,
        )
        return emb, None

    # ---- ações (resgates) ----
    async def do_action(self, interaction: discord.Interaction, action: str) -> None:
        async with session_scope() as session:
            user = await helpers.fetch_user(session, self.author_id)
            if action == "daily":
                ok, msg = _claim_daily(user)
                self.flash = msg
            else:  # quests
                ganhos = []
                for q, cur, done, claimed in quest_state(user):
                    if done and not claimed:
                        c = claim_quest(user, q.key)
                        if c:
                            user.coins += c.reward_coins
                            helpers.grant_trainer_xp(user, c.reward_xp)
                            ganhos.append(c)
                if ganhos:
                    tc = sum(q.reward_coins for q in ganhos)
                    tx = sum(q.reward_xp for q in ganhos)
                    self.flash = f"🎉 +{tc:,}🪙 e +{tx} XP por {len(ganhos)} missão(ões)!"
                else:
                    self.flash = "Nenhuma missão concluída para resgatar ainda."
        await self.show(interaction)


# --------------------------------------------------------------------------
#  Botões
# --------------------------------------------------------------------------
class NavBtn(discord.ui.Button):
    def __init__(self, view: HubView, target, label, emoji, style, row):
        super().__init__(label=label, emoji=emoji, style=style, row=row)
        self._hub, self._target = view, target

    async def callback(self, interaction: discord.Interaction) -> None:
        self._hub.goto(self._target)
        await self._hub.show(interaction)


class PageBtn(discord.ui.Button):
    def __init__(self, view: HubView, delta, emoji):
        super().__init__(emoji=emoji, style=discord.ButtonStyle.secondary, row=0)
        self._hub, self._delta = view, delta

    async def callback(self, interaction: discord.Interaction) -> None:
        self._hub.page += self._delta
        await self._hub.show(interaction)


class ActionBtn(discord.ui.Button):
    def __init__(self, view: HubView, action, label, emoji, style):
        super().__init__(label=label, emoji=emoji, style=style, row=0)
        self._hub, self._action = view, action

    async def callback(self, interaction: discord.Interaction) -> None:
        await self._hub.do_action(interaction, self._action)


class CloseBtn(discord.ui.Button):
    def __init__(self, view: HubView, row=1):
        super().__init__(label="Fechar", emoji="❌", style=discord.ButtonStyle.danger, row=row)
        self._hub = view

    async def callback(self, interaction: discord.Interaction) -> None:
        for c in self._hub.children:
            c.disabled = True
        await interaction.response.edit_message(
            content="Painel fechado. Abra de novo com `/menu`. 👋", embed=None,
            view=self._hub, attachments=[])
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
        view = HubView(ctx.author.id, ctx.prefix)
        await view.send_first(ctx, ephemeral=ephemeral)

    @commands.command(name="sync")
    @commands.is_owner()
    async def sync(self, ctx: commands.Context) -> None:
        """(Dono) Sincroniza os comandos de barra (/) neste servidor."""
        self.bot.tree.copy_global_to(guild=ctx.guild)
        synced = await self.bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ {len(synced)} comando(s) de barra sincronizados neste servidor.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Hub(bot))
